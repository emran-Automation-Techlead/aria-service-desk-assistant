"""PHI/PII-safe wrapper: scrub sensitive patterns before any content leaves
the process (an LLM prompt, a Confluence page, a Jira ticket, a log line).

This is a defensive redaction layer, not a compliance certification — it
catches the common structured leaks (SSNs, emails, phone numbers, card
numbers, MRNs) so ARIA never round-trips them through a third-party API
or an LLM provider.
"""
import re
from typing import List, Tuple
from models import RedactionNote

_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("PHONE", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("MRN", re.compile(r"\bMRN[:#]?\s*\d{5,10}\b", re.IGNORECASE)),
    ("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def redact(text: str) -> Tuple[str, List[RedactionNote]]:
    """Replace sensitive substrings with [REDACTED-<TYPE>] tokens.

    Returns the cleaned text plus a per-type count so the caller can
    surface an audit trail without ever re-exposing the raw values.
    """
    clean = text
    notes: List[RedactionNote] = []
    for label, pattern in _PATTERNS:
        matches = pattern.findall(clean)
        if matches:
            clean = pattern.sub(f"[REDACTED-{label}]", clean)
            notes.append(RedactionNote(type=label, count=len(matches)))
    return clean, notes


def redact_history(history) -> Tuple[list, List[RedactionNote]]:
    """Redact every message in a chat history, merging redaction counts."""
    cleaned = []
    totals: dict = {}
    for msg in history:
        clean_content, notes = redact(msg.content)
        cleaned.append(type(msg)(role=msg.role, content=clean_content))
        for n in notes:
            totals[n.type] = totals.get(n.type, 0) + n.count
    return cleaned, [RedactionNote(type=t, count=c) for t, c in totals.items()]
