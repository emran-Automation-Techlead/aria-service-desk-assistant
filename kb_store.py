"""Local JSON-backed knowledge base store.

Doubles as the offline/mock backing store for Confluence: real Confluence
integration (confluence_client.py) reads/writes here when aria_mock_mode is
on, so ARIA's "auto-draft an article when nothing is found" behavior stays
demo-able without a live Confluence tenant, and the drafted article is
immediately searchable on the next question.
"""
import json
from pathlib import Path
from typing import List
from models import KBArticle, Team

_DATA_PATH = Path(__file__).parent / "data" / "mock_kb.json"


def _load_raw() -> List[dict]:
    if not _DATA_PATH.exists():
        return []
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def load_all() -> List[KBArticle]:
    return [KBArticle(**a) for a in _load_raw()]


def load_for_team(team: Team) -> List[KBArticle]:
    return [a for a in load_all() if a.team == team]


def append(article: KBArticle) -> None:
    raw = _load_raw()
    raw.append(article.model_dump(mode="json"))
    _DATA_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def next_id(team: Team) -> str:
    prefix = {
        Team.SERVICE_DESK: "SD",
        Team.COMMAND_CENTER: "CMD",
        Team.NETWORK: "NET",
        Team.LINUX: "LNX",
        Team.DATABASE: "DBA",
        Team.WINDOWS_ENGINEERING: "WIN",
    }[team]
    existing = [a.id for a in load_for_team(team) if a.id.startswith(prefix)]
    n = len(existing) + 1
    return f"{prefix}-{n:03d}"
