import json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from models import ChatRequest, ChatResponse, TicketRequest, TicketResponse, TEAM_META
import phi_filter
import guardrails
import knowledge_agent
import ticket_writer
import jira_client
import okta_client

app = FastAPI(title="ARIA — Internal Knowledge & Ticketing Assistant")

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def root():
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/teams")
async def list_teams():
    return [{"id": team.value, "label": meta["label"]} for team, meta in TEAM_META.items()]


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        await guardrails.screen(req.message)
    except guardrails.GuardrailViolation as violation:
        return ChatResponse(answer=violation.message, source="blocked")

    clean_message, msg_redactions = phi_filter.redact(req.message)
    clean_history, hist_redactions = phi_filter.redact_history(req.history)

    result = await knowledge_agent.answer(req.team, clean_message, clean_history)
    result.redactions = msg_redactions + hist_redactions
    return result


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE variant of /api/chat: emits status events (probing/searching/
    drafting/...), then token-by-token delta events as the answer is
    generated, then one final done event — what the chat UI's blinking
    cursor and "musing" indicator render live. Runs guardrails.screen()
    on the raw message first and short-circuits with a refusal if it's
    flagged (PHI/PII, sexual content, or a security-risk request)."""
    clean_history, hist_redactions = phi_filter.redact_history(req.history)

    async def event_gen():
        try:
            await guardrails.screen(req.message)
        except guardrails.GuardrailViolation as violation:
            yield f"data: {json.dumps({'type': 'status', 'value': 'blocked'})}\n\n"
            yield f"data: {json.dumps({'type': 'delta', 'value': violation.message})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'source': 'blocked', 'article_title': None, 'article_url': None, 'doc_type': None, 'confidence': None, 'redactions': [], 'guardrail_category': violation.category})}\n\n"
            return

        clean_message, msg_redactions = phi_filter.redact(req.message)
        redactions = [r.model_dump() for r in (msg_redactions + hist_redactions)]
        async for event in knowledge_agent.stream_answer(req.team, clean_message, clean_history):
            if event["type"] == "done":
                event = {**event, "redactions": redactions}
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/api/ticket", response_model=TicketResponse)
async def log_ticket(req: TicketRequest):
    transcript = "\n".join(m.content for m in req.history)
    try:
        await guardrails.screen(transcript)
    except guardrails.GuardrailViolation as violation:
        raise HTTPException(status_code=400, detail=violation.message)

    team_label = TEAM_META[req.team]["label"]
    clean_history, redactions = phi_filter.redact_history(req.history)
    clean_email = None
    if req.user_email:
        clean_email, email_redactions = phi_filter.redact(req.user_email)
        redactions = redactions + email_redactions

    drafted = await ticket_writer.build_ticket(team_label, clean_history)

    requester = await okta_client.lookup_user(req.user_email)
    description = drafted["description"]
    if requester:
        description = f"Requester: {requester['display_name']} ({requester['department']})\n\n{description}"

    ticket = await jira_client.create_ticket(
        team=req.team,
        summary=drafted["summary"],
        description=description,
        priority=drafted["priority"],
        reporter_email=clean_email,
    )

    return TicketResponse(
        ticket_key=ticket["ticket_key"],
        ticket_url=ticket["ticket_url"],
        summary=ticket["summary"],
        description=ticket["description"],
        priority=ticket["priority"],
        redactions=redactions,
    )


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    from config import settings
    uvicorn.run("main:app", host="0.0.0.0", port=settings.aria_port, reload=False)
