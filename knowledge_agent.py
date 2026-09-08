"""RAG-lite over each team's Confluence space: answer from existing
articles, or hand off to the writer to draft and publish a new one when
nothing matches."""
import json
import openai
from models import Team, TEAM_META, ChatMessage, ChatResponse
from prompts import (
    ARIA_SYSTEM, answer_or_not_found_prompt,
    DRAFT_ARTICLE_SYSTEM, draft_article_prompt,
)
from config import settings
import confluence_client

_oai = openai.AsyncOpenAI(api_key=settings.openai_api_key)


def _articles_text(articles) -> str:
    return "\n\n".join(
        f"[{a.id}] {a.title}\n{a.body}" for a in articles
    )


def _history_text(history: list[ChatMessage]) -> str:
    return "\n".join(f"{m.role}: {m.content}" for m in history[-6:])


async def answer(team: Team, question: str, history: list[ChatMessage]) -> ChatResponse:
    team_label = TEAM_META[team]["label"]
    articles = await confluence_client.search(team)

    response = await _oai.chat.completions.create(
        model=settings.aria_model,
        messages=[
            {"role": "system", "content": ARIA_SYSTEM},
            {"role": "user", "content": answer_or_not_found_prompt(team_label, question, _articles_text(articles))},
        ],
        response_format={"type": "json_object"},
        max_tokens=800,
    )
    data = json.loads(response.choices[0].message.content or "{}")

    if data.get("found"):
        matched = next((a for a in articles if a.id == data.get("article_id")), None)
        return ChatResponse(
            answer=data.get("answer", ""),
            source="knowledge_base",
            article_title=matched.title if matched else None,
            article_url=matched.url if matched else None,
        )

    return await _draft_and_publish(team, team_label, question, history)


async def _draft_and_publish(team: Team, team_label: str, question: str, history: list[ChatMessage]) -> ChatResponse:
    draft_response = await _oai.chat.completions.create(
        model=settings.aria_model,
        messages=[
            {"role": "system", "content": DRAFT_ARTICLE_SYSTEM},
            {"role": "user", "content": draft_article_prompt(team_label, question, _history_text(history))},
        ],
        response_format={"type": "json_object"},
        max_tokens=900,
    )
    draft = json.loads(draft_response.choices[0].message.content or "{}")
    title = draft.get("title", question[:80])
    body = draft.get("body", "")

    article = await confluence_client.publish_article(team, title, body)

    answer_text = (
        f"I couldn't find an existing article for that, so I drafted and published one: "
        f"**{article.title}**.\n\n{body}"
    )
    return ChatResponse(
        answer=answer_text,
        source="drafted_article",
        article_title=article.title,
        article_url=article.url,
    )
