"""Confluence integration: search team space, publish an article when the
knowledge base has no answer.

Runs in one of two modes:
  - mock (default): reads/writes kb_store.py's local JSON file. Every
    auto-drafted article is appended there, so the KB self-heals across
    the session with zero external dependency.
  - live: once confluence_base_url/email/api_token are set and
    aria_mock_mode=false, search hits the real Confluence Cloud REST API
    (CQL search) and publishing creates a real page via the content API.
"""
import aiohttp
from typing import List, Optional
from models import KBArticle, Team, TEAM_META
from config import settings
import kb_store


async def search(team: Team) -> List[KBArticle]:
    """Return every article available to a team's space."""
    if settings.aria_mock_mode or not settings.confluence_base_url:
        return kb_store.load_for_team(team)
    return await _live_search(team)


async def publish_article(team: Team, title: str, body: str) -> KBArticle:
    """Publish a newly drafted article and return the stored/created record."""
    if settings.aria_mock_mode or not settings.confluence_base_url:
        article = KBArticle(
            id=kb_store.next_id(team),
            team=team,
            title=title,
            tags=[],
            body=body,
            url=f"https://confluence.company.internal/wiki/spaces/{TEAM_META[team]['confluence_space']}/{title.replace(' ', '+')}",
            source="auto-drafted",
        )
        kb_store.append(article)
        return article
    return await _live_publish(team, title, body)


async def _live_search(team: Team) -> List[KBArticle]:
    space = TEAM_META[team]["confluence_space"]
    url = f"{settings.confluence_base_url.rstrip('/')}/wiki/rest/api/content"
    auth = aiohttp.BasicAuth(settings.confluence_email, settings.confluence_api_token)
    params = {"spaceKey": space, "expand": "body.storage", "limit": 50}
    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
    articles = []
    for r in data.get("results", []):
        articles.append(KBArticle(
            id=r["id"],
            team=team,
            title=r["title"],
            body=r.get("body", {}).get("storage", {}).get("value", ""),
            url=f"{settings.confluence_base_url.rstrip('/')}/wiki{r.get('_links', {}).get('webui', '')}",
            source="seed",
        ))
    return articles


async def _live_publish(team: Team, title: str, body: str) -> KBArticle:
    space = TEAM_META[team]["confluence_space"]
    url = f"{settings.confluence_base_url.rstrip('/')}/wiki/rest/api/content"
    auth = aiohttp.BasicAuth(settings.confluence_email, settings.confluence_api_token)
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space},
        "body": {"storage": {"value": f"<p>{body}</p>", "representation": "storage"}},
    }
    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    page_url = f"{settings.confluence_base_url.rstrip('/')}/wiki{data.get('_links', {}).get('webui', '')}"
    return KBArticle(
        id=data["id"], team=team, title=title, body=body, url=page_url, source="auto-drafted"
    )
