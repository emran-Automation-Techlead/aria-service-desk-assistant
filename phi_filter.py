"""Soft PII redaction: mask low-sensitivity, operationally-necessary
contact details (email, phone, IP) before any content leaves the process,
while still letting the message through — a ticket needs a reporter's
email, a network issue needs an IP. Keep audit counts, but don't block.

High-sensitivity data — SSNs, card numbers, medical record numbers — is
NOT handled here. That's a hard refusal, not a mask-and-continue, and
lives in guardrails.py instead.
"""
import re
from typing import List, Tuple
from models import RedactionNote

_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("PHONE", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
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
