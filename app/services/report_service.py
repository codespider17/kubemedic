from typing import Any, Protocol

from pydantic import ValidationError

from app.domain.incident import IncidentStatus
from app.domain.report import AnalysisReport, RecommendedAction, RootCause
from app.providers.deepseek_provider import (
    DeepSeekError,
    DeepSeekProvider,
    ProviderOutput,
)
from app.repositories.analysis_repository import list_analysis_results
from app.repositories.evidence_repository import list_evidence
from app.repositories.report_repository import get_report, save_report
from app.services.incident_manager import get_incident, transition_incident
from app.services.prompt_builder import build_messages

ALLOWED_CODES = {
    "CONTAINER_OOM_KILLED",
    "CONTAINER_CRASH_LOOP_BACKOFF",
    "IMAGE_PULL_FAILED",
    "CONTAINER_PROBE_FAILED",
    "POD_SCHEDULING_FAILED",
    "SERVICE_NO_READY_ENDPOINTS",
    "UNKNOWN",
}


class Provider(Protocol):
    def generate(
        self,
        messages: list[dict[str, str]],
    ) -> ProviderOutput:
        ...


def _validate_references(
    report: AnalysisReport,
    incident_id: str,
    evidence: list[dict[str, Any]],
) -> None:
    if report.incident_id != incident_id:
        raise ValueError("report incident_id mismatch")
    valid_ids = {item["evidence_id"] for item in evidence}
    for cause in report.root_causes:
        if cause.code not in ALLOWED_CODES:
            raise ValueError(f"unsupported root cause code: {cause.code}")
        unknown_ids = set(cause.evidence_ids) - valid_ids
        if unknown_ids:
            raise ValueError(
                f"unknown evidence ids: {sorted(unknown_ids)}"
            )


def build_fallback_report(
    incident: dict[str, Any],
    results: list[dict[str, Any]],
    error: str,
) -> AnalysisReport:
    matched = [item for item in results if item["matched"]]
    causes = [
        RootCause(
            code=item["root_cause_code"],
            description=item["summary"],
            confidence=item["confidence"],
            evidence_ids=item["evidence_ids"],
        )
        for item in matched
    ]
    if not causes:
        causes = [
            RootCause(
                code="UNKNOWN",
                description="现有确定性规则未命中，需要补充证据",
                confidence=0.2,
                evidence_ids=[],
            )
        ]
    checks = list(
        dict.fromkeys(
            check
            for item in matched
            for check in item["suggested_checks"]
        )
    )
    actions = [
        RecommendedAction(
            title="只读核查",
            description=check,
            risk="low",
            requires_approval=True,
        )
        for check in checks[:6]
    ]
    return AnalysisReport(
        incident_id=incident["id"],
        summary="DeepSeek不可用，报告由规则Analyzer生成",
        root_causes=causes,
        recommended_actions=actions,
        unknowns=[f"DeepSeek失败：{error}"],
        analysis_mode="rules_fallback",
        provider="deepseek",
        model="unavailable",
        provider_error=error[:500],
    )


def generate_report(
    incident_id: str,
    provider: Provider | None = None,
) -> dict[str, Any]:
    incident = get_incident(incident_id)
    if incident is None:
        raise KeyError(incident_id)
    if incident["status"] != IncidentStatus.ANALYZING:
        raise ValueError(
            "incident must be ANALYZING before report generation, "
            f"got {incident['status']}"
        )
    evidence = list_evidence(incident_id)
    results = list_analysis_results(incident_id)
    if not evidence:
        raise ValueError("incident has no evidence")
    if not results:
        raise ValueError("incident has no analyzer results")

    try:
        selected_provider = provider or DeepSeekProvider()
        output = selected_provider.generate(
            build_messages(incident, evidence, results)
        )
        report = AnalysisReport(
            **output.payload,
            analysis_mode="deepseek",
            provider="deepseek",
            model=output.model,
            prompt_tokens=output.prompt_tokens,
            completion_tokens=output.completion_tokens,
            total_tokens=output.total_tokens,
        )
        _validate_references(report, incident_id, evidence)
    except (DeepSeekError, ValidationError, ValueError) as error:
        report = build_fallback_report(
            incident,
            results,
            f"{type(error).__name__}: {error}",
        )

    saved = save_report(report)
    transition_incident(
        incident_id,
        IncidentStatus.REPORTED,
        f"report generated with mode={report.analysis_mode}",
    )
    return saved


def find_report(incident_id: str) -> dict[str, Any] | None:
    if get_incident(incident_id) is None:
        raise KeyError(incident_id)
    return get_report(incident_id)
