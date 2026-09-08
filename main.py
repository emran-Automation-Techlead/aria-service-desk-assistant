from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from models import ChatRequest, ChatResponse, TicketRequest, TicketResponse, TEAM_META
import phi_filter
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
    clean_message, msg_redactions = phi_filter.redact(req.message)
    clean_history, hist_redactions = phi_filter.redact_history(req.history)

    result = await knowledge_agent.answer(req.team, clean_message, clean_history)
    result.redactions = msg_redactions + hist_redactions
    return result


@app.post("/api/ticket", response_model=TicketResponse)
async def log_ticket(req: TicketRequest):
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
