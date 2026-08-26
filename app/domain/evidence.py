import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MAX_TEXT_BYTES = 64 * 1024
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"),
    re.compile(
        r"(?i)((?:password|token|api[_-]?key|secret)\s*[=:]\s*)[^\s]+"
    ),
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def redact_sensitive_text(text: str) -> str:
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def truncate_text(text: str, max_bytes: int = MAX_TEXT_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = "\n...[TRUNCATED]"
    shortened = encoded[: max_bytes - len(suffix)].decode(
        "utf-8",
        errors="ignore",
    )
    return shortened + suffix


class Evidence(BaseModel):
    evidence_id: str = Field(
        default_factory=lambda: f"ev-{uuid4().hex}"
    )
    incident_id: str
    source: str
    resource_ref: str
    summary: str
    observed_at: str = Field(default_factory=utc_now_iso)
    raw: Any
    sensitivity: Literal["normal", "redacted"] = "normal"
