from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class Team(str, Enum):
    SERVICE_DESK = "service_desk"
    COMMAND_CENTER = "command_center"
    NETWORK = "network"
    LINUX = "linux"
    DATABASE = "database"
    WINDOWS_ENGINEERING = "windows_engineering"


TEAM_META = {
    Team.SERVICE_DESK: {
        "label": "IT Service Desk",
        "jira_project": "ITSD",
        "confluence_space": "ITSD",
    },
    Team.COMMAND_CENTER: {
        "label": "Command Center / NOC",
        "jira_project": "CMD",
        "confluence_space": "CMDCTR",
    },
    Team.NETWORK: {
        "label": "Network Team",
        "jira_project": "NET",
        "confluence_space": "NETENG",
    },
    Team.LINUX: {
        "label": "Linux Team",
        "jira_project": "LNX",
        "confluence_space": "LINUXOPS",
    },
    Team.DATABASE: {
        "label": "Database Team",
        "jira_project": "DBA",
        "confluence_space": "DBAOPS",
    },
    Team.WINDOWS_ENGINEERING: {
        "label": "Windows Engineering",
        "jira_project": "WINENG",
        "confluence_space": "WINENG",
    },
}


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    team: Team
    message: str
    history: List[ChatMessage] = Field(default_factory=list)
    user_email: Optional[str] = None


class RedactionNote(BaseModel):
    type: str
    count: int


class ChatResponse(BaseModel):
    answer: str
    source: str  # "knowledge_base" | "drafted_article"
    article_title: Optional[str] = None
    article_url: Optional[str] = None
    redactions: List[RedactionNote] = Field(default_factory=list)


class TicketRequest(BaseModel):
    team: Team
    history: List[ChatMessage]
    user_email: Optional[str] = None


class TicketResponse(BaseModel):
    ticket_key: str
    ticket_url: str
    summary: str
    description: str
    priority: str
    redactions: List[RedactionNote] = Field(default_factory=list)


class KBArticle(BaseModel):
    id: str
    team: Team
    title: str
    tags: List[str] = Field(default_factory=list)
    body: str
    url: str = ""
    source: str = "seed"  # "seed" | "auto-drafted"
