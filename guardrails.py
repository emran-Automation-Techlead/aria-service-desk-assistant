"""Hard content-safety guardrails, checked before anything reaches an LLM
call, Confluence, or Jira. Three blocking categories, all refuse outright
rather than mask-and-continue:

  1. High-sensitivity PHI/PII — SSNs, card numbers, medical record numbers.
     (Low-sensitivity contact info like email/phone stays soft-redacted in
     phi_filter.py, since ticket routing genuinely needs it.)
  2. Sexual/nudity content and other unsafe categories — via OpenAI's
     Moderation API.
  3. Security-risk requests — credential theft, bypassing auth/security
     tooling, malware, exfiltration — via a curated keyword heuristic,
     since moderation models don't reliably flag IT-specific phrasing like
     "bypass MFA on another user's account" as illicit.
"""
import re
import openai
from config import settings

_oai = openai.AsyncOpenAI(api_key=settings.openai_api_key)

_HIGH_SENSITIVITY_PATTERNS = [
    ("Social Security Number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card number", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("medical record number", re.compile(r"\bMRN[:#]?\s*\d{5,10}\b", re.IGNORECASE)),
]

_SECURITY_RISK_PATTERNS = [
    re.compile(r"\b(give|share|send)\s+me\s+(the\s+)?(admin|root|domain admin)\s+password", re.I),
    re.compile(r"\bbypass\s+(mfa|2fa|authentication|security\s+controls?)\b", re.I),
    re.compile(r"\b(disable|turn off|kill)\s+(antivirus|edr|firewall|logging|audit(ing)?)\b.{0,40}\b(permanently|so\s+(it|nobody|no\s*one)\s+(won'?t|does\s*n'?t|doesn'?t)\s+notice)\b", re.I),
    re.compile(r"\b(exfiltrate|steal|dump)\s+(the\s+)?(customer|user|employee)?\s*(database|data|credentials|passwords)\b", re.I),
    re.compile(r"\bcreate\s+(a\s+)?(ransomware|keylogger|rootkit|malware)\b", re.I),
    re.compile(r"\b(crack|brute[- ]?force)\s+(a\s+|the\s+)?(user'?s?\s+)?password\b", re.I),
    re.compile(r"\baccess\s+(another|someone else'?s|a coworker'?s)\s+(account|mailbox|files)\s+without\s+(their\s+)?(permission|knowledge|consent)\b", re.I),
]

_SEXUAL_REFUSAL = "ARIA is a work knowledge assistant and doesn't engage with sexual content. Please rephrase your IT question."
_SECURITY_REFUSAL = "That request looks like it's asking for something harmful or illicit. ARIA won't help with that."

# OpenAI's own `flagged` boolean uses thresholds tuned for open consumer
# chat, which let phrases like "send me nude pictures" (sexual score 0.57)
# through. This is a zero-tolerance internal tool, so score against lower,
# explicitly-chosen thresholds instead of trusting `flagged` — validated
# against common IT phrasing ("kill the process", "terminate a connection")
# scoring ~0.0-0.05 on these categories, well clear of the cutoffs below.
_CATEGORY_THRESHOLDS = {
    "sexual": (0.25, _SEXUAL_REFUSAL),
    "sexual/minors": (0.1, _SEXUAL_REFUSAL),
    "illicit": (0.3, _SECURITY_REFUSAL),
    "illicit/violent": (0.2, _SECURITY_REFUSAL),
}


class GuardrailViolation(Exception):
    def __init__(self, category: str, message: str):
        self.category = category
        self.message = message
        super().__init__(message)


def _check_high_sensitivity_pii(text: str) -> None:
    for label, pattern in _HIGH_SENSITIVITY_PATTERNS:
        if pattern.search(text):
            raise GuardrailViolation(
                "phi_pii",
                f"That message appears to contain a {label}. ARIA can't process Social "
                "Security numbers, card numbers, or medical record numbers — please remove "
                "that detail and resend."
            )


def _check_security_risk_keywords(text: str) -> None:
    for pattern in _SECURITY_RISK_PATTERNS:
        if pattern.search(text):
            raise GuardrailViolation(
                "security_risk",
                "That request looks like it's asking for something that could bypass security "
                "controls or expose credentials/data. ARIA won't help with that — please open a "
                "ticket with the Security team if this is a legitimate need."
            )


async def _check_moderation(text: str) -> None:
    result = await _oai.moderations.create(model="omni-moderation-latest", input=text)
    scores = result.results[0].category_scores.model_dump()
    for category, (threshold, refusal) in _CATEGORY_THRESHOLDS.items():
        if (scores.get(category) or 0.0) >= threshold:
            raise GuardrailViolation(
                "sexual_content" if category.startswith("sexual") else "security_risk",
                refusal,
            )


async def screen(text: str) -> None:
    """Raises GuardrailViolation if the message should be refused outright.
    Call with the raw (pre-redaction) message so the high-sensitivity PII
    check still sees the pattern before phi_filter would mask it."""
    if not text or not text.strip():
        return
    _check_high_sensitivity_pii(text)
    _check_security_risk_keywords(text)
    await _check_moderation(text)
