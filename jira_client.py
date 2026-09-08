"""Jira Service Desk integration: create a ticket from a chat-derived
summary/description.

Mock mode (default) appends to a local JSON store so the "Log as Ticket"
flow is fully demo-able offline. Live mode posts to the real Jira Cloud
REST API once jira_base_url/email/api_token are set and aria_mock_mode is
false.
"""
import json
from pathlib import Path
from typing import Optional
import aiohttp
from models import Team, TEAM_META
from config import settings

_TICKETS_PATH = Path(__file__).parent / "data" / "mock_tickets.json"


def _load_tickets() -> list:
    if not _TICKETS_PATH.exists():
        return []
    return json.loads(_TICKETS_PATH.read_text(encoding="utf-8"))


def _save_tickets(tickets: list) -> None:
    _TICKETS_PATH.write_text(json.dumps(tickets, indent=2), encoding="utf-8")


async def create_ticket(
    team: Team, summary: str, description: str, priority: str = "Medium",
    reporter_email: Optional[str] = None,
) -> dict:
    if settings.aria_mock_mode or not settings.jira_base_url:
        return _mock_create(team, summary, description, priority, reporter_email)
    return await _live_create(team, summary, description, priority, reporter_email)


def _mock_create(team, summary, description, priority, reporter_email) -> dict:
    project = TEAM_META[team]["jira_project"]
    tickets = _load_tickets()
    n = sum(1 for t in tickets if t["ticket_key"].startswith(project)) + 1
    ticket_key = f"{project}-{n}"
    ticket = {
        "ticket_key": ticket_key,
        "ticket_url": f"https://company.atlassian.net/browse/{ticket_key}",
        "project": project,
        "summary": summary,
        "description": description,
        "priority": priority,
        "reporter_email": reporter_email,
    }
    tickets.append(ticket)
    _save_tickets(tickets)
    return ticket


async def _live_create(team, summary, description, priority, reporter_email) -> dict:
    project = TEAM_META[team]["jira_project"]
    url = f"{settings.jira_base_url.rstrip('/')}/rest/api/2/issue"
    auth = aiohttp.BasicAuth(settings.jira_email, settings.jira_api_token)
    payload = {
        "fields": {
            "project": {"key": project},
            "summary": summary,
            "description": description,
            "issuetype": {"name": "Task"},
            "priority": {"name": priority},
        }
    }
    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    ticket_key = data["key"]
    return {
        "ticket_key": ticket_key,
        "ticket_url": f"{settings.jira_base_url.rstrip('/')}/browse/{ticket_key}",
        "project": project,
        "summary": summary,
        "description": description,
        "priority": priority,
        "reporter_email": reporter_email,
    }
