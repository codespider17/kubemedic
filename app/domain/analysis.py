from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from app.domain.evidence import utc_now_iso


class AnalyzerResult(BaseModel):
    result_id: str = Field(
        default_factory=lambda: f"ana-{uuid4().hex}"
    )
    incident_id: str
    analyzer: str
    matched: bool
    root_cause_code: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    suggested_checks: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def validate_match(self) -> "AnalyzerResult":
        if self.matched and self.root_cause_code is None:
            raise ValueError("matched result requires root_cause_code")
        if not self.matched and self.root_cause_code is not None:
            raise ValueError("unmatched result cannot have root_cause_code")
        return self
