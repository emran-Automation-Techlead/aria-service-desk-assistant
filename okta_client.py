"""Okta identity lookup, used to attach a requester's department/team to a
ticket without ARIA ever handling more than non-sensitive profile fields
(name, department, manager) — the PHI-safe wrapper this project is built
around never requests or forwards Okta attributes beyond those.
"""
from typing import Optional
import aiohttp
from config import settings

_MOCK_DIRECTORY = {
    "emranali.emran82@gmail.com": {"display_name": "Emran Ali", "department": "IT Operations", "manager": "N/A"},
}


async def lookup_user(email: Optional[str]) -> Optional[dict]:
    if not email:
        return None
    if settings.aria_mock_mode or not settings.okta_domain:
        return _MOCK_DIRECTORY.get(email, {"display_name": email.split("@")[0], "department": "Unknown", "manager": "Unknown"})
    return await _live_lookup(email)


async def _live_lookup(email: str) -> Optional[dict]:
    url = f"https://{settings.okta_domain}/api/v1/users/{email}"
    headers = {"Authorization": f"SSWS {settings.okta_api_token}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            data = await resp.json()
    profile = data.get("profile", {})
    return {
        "display_name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
        "department": profile.get("department", "Unknown"),
        "manager": profile.get("manager", "Unknown"),
    }
