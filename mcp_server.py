"""Exposes ARIA's knowledge and ticketing tools over MCP (stdio transport)
so any MCP-compatible host — Claude Desktop, Claude Code, another agent —
can search the knowledge base, draft/publish Confluence articles, create
Jira tickets, and look up Okta identities as first-class tools, on top of
the same FastAPI backend in main.py.

Run with: python mcp_server.py
"""
from dotenv import load_dotenv
load_dotenv()

try:
    from mcp.server.fastmcp import FastMCP  # mcp SDK 1.x
except ImportError:
    from mcp.server import MCPServer as FastMCP  # mcp SDK 2.x renamed FastMCP -> MCPServer

from models import Team, TEAM_META, ChatMessage
import phi_filter
import knowledge_agent
import ticket_writer
import jira_client
import okta_client
import confluence_client

mcp = FastMCP("aria")


@mcp.tool()
async def search_knowledge_base(team: str, question: str) -> str:
    """Search a team's Confluence knowledge base and answer from it, or
    draft and publish a new article if nothing matches.

    team: one of service_desk, command_center, network, linux, database, windows_engineering
    question: the user's question
    """
    team_enum = Team(team)
    clean_question, _ = phi_filter.redact(question)
    result = await knowledge_agent.answer(team_enum, clean_question, [])
    return result.answer


@mcp.tool()
async def create_confluence_article(team: str, title: str, body: str) -> str:
    """Publish a new Confluence article directly (bypassing the draft step).

    team: one of service_desk, command_center, network, linux, database, windows_engineering
    """
    team_enum = Team(team)
    clean_body, _ = phi_filter.redact(body)
    article = await confluence_client.publish_article(team_enum, title, clean_body)
    return f"Published {article.title} at {article.url}"


@mcp.tool()
async def create_jira_ticket(team: str, conversation: str, user_email: str = "") -> str:
    """Turn a raw conversation transcript into a well-formed Jira ticket and file it.

    team: one of service_desk, command_center, network, linux, database, windows_engineering
    conversation: newline-separated "role: message" lines
    user_email: optional reporter email, used only for Okta department lookup
    """
    team_enum = Team(team)
    team_label = TEAM_META[team_enum]["label"]

    history = []
    for line in conversation.splitlines():
        if ":" in line:
            role, content = line.split(":", 1)
            history.append(ChatMessage(role=role.strip(), content=content.strip()))
    clean_history, _ = phi_filter.redact_history(history)

    drafted = await ticket_writer.build_ticket(team_label, clean_history)
    requester = await okta_client.lookup_user(user_email or None)
    description = drafted["description"]
    if requester:
        description = f"Requester: {requester['display_name']} ({requester['department']})\n\n{description}"

    ticket = await jira_client.create_ticket(
        team=team_enum, summary=drafted["summary"], description=description,
        priority=drafted["priority"], reporter_email=user_email or None,
    )
    return f"Created {ticket['ticket_key']} ({ticket['priority']}): {ticket['summary']} — {ticket['ticket_url']}"


@mcp.tool()
async def lookup_okta_user(email: str) -> str:
    """Look up a user's display name and department in Okta (PHI-safe: no
    sensitive attributes beyond name/department/manager are ever returned)."""
    clean_email, _ = phi_filter.redact(email)
    if clean_email != email:
        return "Refused: input did not look like a plain email address."
    user = await okta_client.lookup_user(email)
    if not user:
        return "No matching user found."
    return f"{user['display_name']} — {user['department']} (manager: {user['manager']})"


if __name__ == "__main__":
    mcp.run(transport="stdio")
