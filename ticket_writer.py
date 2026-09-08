"""Turns the raw back-and-forth of a chat into a clean, professionally
worded Jira ticket: the "log chat" feature — it takes whatever the user
typed, however informal, and produces meaningful sentences a technician
can act on without re-reading the whole conversation."""
import json
import openai
from models import ChatMessage
from prompts import TICKET_WRITER_SYSTEM, ticket_writer_prompt
from config import settings

_oai = openai.AsyncOpenAI(api_key=settings.openai_api_key)


async def build_ticket(team_label: str, history: list[ChatMessage]) -> dict:
    conversation_text = "\n".join(f"{m.role}: {m.content}" for m in history)

    response = await _oai.chat.completions.create(
        model=settings.aria_model,
        messages=[
            {"role": "system", "content": TICKET_WRITER_SYSTEM},
            {"role": "user", "content": ticket_writer_prompt(team_label, conversation_text)},
        ],
        response_format={"type": "json_object"},
        max_tokens=700,
    )
    data = json.loads(response.choices[0].message.content or "{}")
    return {
        "summary": data.get("summary", "Support request from ARIA chat"),
        "description": data.get("description", conversation_text),
        "priority": data.get("priority", "Medium"),
    }
