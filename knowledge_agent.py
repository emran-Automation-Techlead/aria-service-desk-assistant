"""RAG-lite over each team's Confluence space, with a LangChain probing
layer (probe_agent.py) sitting above the raw model calls:

  1. probe_agent.assess() — is the question specific enough to search? If
     not, ARIA asks ONE clarifying question instead of guessing.
  2. A confidence-scored retrieval loop — decide() scores how well the best
     matching article covers the question; if confidence is low, probe_agent
     .reword() rephrases the search intent and we try again (up to
     MAX_PROBE_ROUNDS), instead of settling for a weak match.
  3. If nothing clears the confidence bar, ARIA drafts and publishes a new
     article instead of presenting a guess.

stream_answer() is an async generator of small event dicts consumed by the
FastAPI SSE endpoint (status while probing/searching/drafting, delta tokens
as the answer streams, then a final done event). answer() collects the same
stream into one ChatResponse for non-chat callers (the MCP server).
"""
import json
from typing import AsyncGenerator, List
import openai
from models import Team, TEAM_META, ChatMessage, ChatResponse
from prompts import (
    ARIA_SYSTEM,
    DECISION_SYSTEM, decision_prompt,
    SYNTHESIZE_SYSTEM, synthesize_prompt,
    DRAFT_TITLE_SYSTEM, draft_title_prompt,
    DRAFT_BODY_SYSTEM, draft_body_prompt,
)
from config import settings
import confluence_client
import probe_agent
import vector_store

_oai = openai.AsyncOpenAI(api_key=settings.openai_api_key)

MAX_PROBE_ROUNDS = 2
CONFIDENCE_THRESHOLD = 0.6


def _history_text(history: List[ChatMessage]) -> str:
    return "\n".join(f"{m.role}: {m.content}" for m in history[-6:])


async def _decide(team: Team, team_label: str, search_intent: str) -> dict:
    """Retrieve the top matching chunks for this search intent (not the
    whole KB) and ask the model whether they answer it."""
    context = vector_store.best_articles_context(team, search_intent)
    response = await _oai.chat.completions.create(
        model=settings.aria_model,
        temperature=settings.aria_temperature,
        messages=[
            {"role": "system", "content": DECISION_SYSTEM},
            {"role": "user", "content": decision_prompt(team_label, search_intent, context)},
        ],
        response_format={"type": "json_object"},
        max_tokens=300,
    )
    data = json.loads(response.choices[0].message.content or "{}")
    return {
        "found": bool(data.get("found")),
        "article_id": data.get("article_id"),
        "confidence": float(data.get("confidence") or 0.0),
    }


async def _best_match(team: Team, team_label: str, search_intent: str):
    """Confidence-scored retrieval loop: reword the query and re-embed a
    fresh vector search when the first pass is weak, instead of accepting
    a low-confidence guess."""
    best_decision = None
    intent = search_intent
    for round_i in range(MAX_PROBE_ROUNDS):
        decision = await _decide(team, team_label, intent)
        if best_decision is None or decision["confidence"] > best_decision["confidence"]:
            best_decision = decision
        if best_decision["confidence"] >= CONFIDENCE_THRESHOLD:
            break
        if round_i < MAX_PROBE_ROUNDS - 1:
            intent = await probe_agent.reword(team_label, search_intent, intent)
    return best_decision


async def stream_answer(team: Team, question: str, history: List[ChatMessage]) -> AsyncGenerator[dict, None]:
    team_label = TEAM_META[team]["label"]

    yield {"type": "status", "value": "probing"}
    probe = await probe_agent.assess(team_label, question, history)

    if not probe.get("clear", True):
        cq = probe.get("clarifying_question") or (
            "Could you share a bit more detail — which system, the exact error or "
            "symptom, and when it started?"
        )
        yield {"type": "status", "value": "asking"}
        yield {"type": "delta", "value": cq}
        yield {"type": "done", "source": "clarifying_question", "article_title": None,
               "article_url": None, "doc_type": None, "confidence": None}
        return

    search_intent = probe.get("search_intent") or question
    yield {"type": "status", "value": "searching"}
    articles = await confluence_client.search(team)
    vector_store.ensure_team_indexed(team, articles)
    decision = await _best_match(team, team_label, search_intent) if articles else {"found": False, "confidence": 0.0, "article_id": None}

    matched = None
    if decision["found"] and decision["confidence"] >= CONFIDENCE_THRESHOLD:
        matched = next((a for a in articles if a.id == decision["article_id"]), None)

    if matched:
        yield {"type": "status", "value": "answering", "article_title": matched.title, "doc_type": matched.doc_type}
        stream = await _oai.chat.completions.create(
            model=settings.aria_model,
            temperature=settings.aria_temperature,
            stream=True,
            messages=[
                {"role": "system", "content": f"{ARIA_SYSTEM}\n\n{SYNTHESIZE_SYSTEM}"},
                {"role": "user", "content": synthesize_prompt(matched.title, matched.body, question)},
            ],
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield {"type": "delta", "value": delta}
        yield {"type": "done", "source": "knowledge_base", "article_title": matched.title,
               "article_url": matched.url, "doc_type": matched.doc_type, "confidence": decision["confidence"]}
        return

    async for event in _draft_and_publish_stream(team, team_label, question, history):
        yield event


async def _draft_and_publish_stream(team: Team, team_label: str, question: str, history: List[ChatMessage]) -> AsyncGenerator[dict, None]:
    yield {"type": "status", "value": "drafting"}

    title_response = await _oai.chat.completions.create(
        model=settings.aria_model,
        temperature=settings.aria_temperature,
        messages=[
            {"role": "system", "content": DRAFT_TITLE_SYSTEM},
            {"role": "user", "content": draft_title_prompt(team_label, question)},
        ],
        response_format={"type": "json_object"},
        max_tokens=60,
    )
    title = json.loads(title_response.choices[0].message.content or "{}").get("title", question[:80])

    yield {"type": "status", "value": "writing_article", "article_title": title}

    body_stream = await _oai.chat.completions.create(
        model=settings.aria_model,
        temperature=settings.aria_temperature,
        stream=True,
        messages=[
            {"role": "system", "content": DRAFT_BODY_SYSTEM},
            {"role": "user", "content": draft_body_prompt(team_label, question, _history_text(history))},
        ],
    )
    body_parts: List[str] = []
    async for chunk in body_stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            body_parts.append(delta)
            yield {"type": "delta", "value": delta}

    body = "".join(body_parts)
    article = await confluence_client.publish_article(team, title, body)
    vector_store.index_article(article)
    yield {"type": "done", "source": "drafted_article", "article_title": article.title,
           "article_url": article.url, "doc_type": article.doc_type, "confidence": None}


async def answer(team: Team, question: str, history: List[ChatMessage]) -> ChatResponse:
    """Non-streaming wrapper over stream_answer, for callers that need one
    ChatResponse instead of an event stream (the MCP server)."""
    text_parts: List[str] = []
    result = ChatResponse(answer="", source="knowledge_base")
    async for event in stream_answer(team, question, history):
        if event["type"] == "delta":
            text_parts.append(event["value"])
        elif event["type"] == "done":
            result = ChatResponse(
                answer="".join(text_parts),
                source=event["source"],
                article_title=event.get("article_title"),
                article_url=event.get("article_url"),
                doc_type=event.get("doc_type"),
                confidence=event.get("confidence"),
            )
    return result
