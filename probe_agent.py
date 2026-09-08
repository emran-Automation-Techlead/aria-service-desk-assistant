"""LangChain layer that sits above the raw OpenAI calls and decides how to
approach a user's issue before ARIA ever touches the knowledge base.

Two jobs:
  1. assess() - reads the message (+ history) and decides whether there's
     enough concrete detail to search confidently. A vague incident report
     ("my thing is broken") gets ONE clarifying question back instead of a
     guessed answer. A clear how-to question passes straight through, along
     with a cleaned-up "search_intent" phrase for retrieval.
  2. reword() - used by knowledge_agent's retrieval loop when the first
     search comes back low-confidence: rephrases the search intent for
     another attempt instead of settling for a weak match.

Both run through LangChain's ChatOpenAI + prompt templates rather than the
raw openai SDK, so this probing/looping step is a distinct, swappable layer
above the model calls knowledge_agent.py makes for retrieval and synthesis.
"""
from typing import List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from models import ChatMessage
from config import settings

_llm = ChatOpenAI(
    model=settings.aria_model,
    temperature=settings.aria_temperature,
    api_key=settings.openai_api_key,
)

_CLARITY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are ARIA's intake triage step for the {team_label} team. Default to clear: "
     "only ask a clarifying question when the message is so vague that a search would "
     "have nothing to go on — e.g. 'my thing is broken', 'it's not working', 'help', "
     "with no named system and no symptom at all. "
     "The moment the user names WHAT is affected (a system, app, or task) and/or HOW it's "
     "failing (an error, symptom, or behavior), that is enough to search on — mark it clear "
     "even if minor details like hostname or OS version are still missing; those can be "
     "asked about later if the search genuinely needs them. "
     "General how-to / request questions ('how do I request X', 'how do I reset Y') are "
     "always clear. If the conversation history already supplies the missing detail, treat "
     "it as clear.\n"
     "Examples that are CLEAR: 'VPN won't connect and the MFA push keeps failing', "
     "'prod-db-03 is at 98% disk usage', 'Outlook is stuck on trying to connect'.\n"
     "Examples that are NOT CLEAR: 'my vpn is broken', 'the server is down', 'nothing works'.\n"
     "Reply with JSON only, no other text: "
     '{{"clear": true|false, "clarifying_question": "<one short question, or null if clear>", '
     '"search_intent": "<the issue restated in the clearest possible search terms>"}}'),
    ("human", "Conversation so far:\n{history}\n\nLatest message: {question}"),
])
_clarity_chain = _CLARITY_PROMPT | _llm | JsonOutputParser()


_REWORD_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are refining a knowledge-base search query for the {team_label} team because the "
     "previous attempt did not confidently match anything. Given the user's original question "
     "and the search phrase already tried, produce ONE new, differently-angled search phrase "
     "(synonyms, more specific terms, or a broader framing) that might match better. "
     "Reply with the phrase only, no punctuation around it, no explanation."),
    ("human", "Original question: {question}\nPrevious search phrase: {previous_intent}"),
])
_reword_chain = _REWORD_PROMPT | _llm | StrOutputParser()


async def assess(team_label: str, question: str, history: List[ChatMessage]) -> dict:
    history_text = "\n".join(f"{m.role}: {m.content}" for m in history[-6:]) or "(none)"
    result = await _clarity_chain.ainvoke({
        "team_label": team_label, "history": history_text, "question": question,
    })
    result.setdefault("clear", True)
    result.setdefault("clarifying_question", None)
    result.setdefault("search_intent", question)
    return result


async def reword(team_label: str, question: str, previous_intent: str) -> str:
    result = await _reword_chain.ainvoke({
        "team_label": team_label, "question": question, "previous_intent": previous_intent,
    })
    return result.strip().strip('"')
