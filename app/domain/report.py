from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.evidence import utc_now_iso


class RootCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)


class RecommendedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    risk: Literal["low", "medium", "high"]
    requires_approval: bool = True


class AnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(
        default_factory=lambda: f"rpt-{uuid4().hex}"
    )
    incident_id: str
    summary: str
    root_causes: list[RootCause] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(
        default_factory=list
    )
    unknowns: list[str] = Field(default_factory=list)
    analysis_mode: Literal["deepseek", "rules_fallback"]
    provider: str = "deepseek"
    model: str
    provider_error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    created_at: str = Field(default_factory=utc_now_iso)
