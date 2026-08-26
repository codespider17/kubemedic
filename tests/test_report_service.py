from typing import Any

from app.providers.deepseek_provider import (
    ProviderOutput,
    RetryableDeepSeekError,
)
from app.services import report_service
from app.services.prompt_builder import build_messages

INCIDENT = {
    "id": "inc-report",
    "status": "ANALYZING",
    "alert_name": "PodCrash",
    "namespace": "demo",
    "workload": "api",
    "pod": "api-1",
    "severity": "warning",
    "occurrence_count": 1,
}
EVIDENCE = [
    {
        "evidence_id": "ev-1",
        "source": "pod_status",
        "resource_ref": "demo/Pod/api-1",
        "summary": "CrashLoopBackOff token=secret-value",
        "raw": {"phase": "Running"},
    }
]
RESULTS = [
    {
        "analyzer": "crash_loop_backoff",
        "matched": True,
        "root_cause_code": "CONTAINER_CRASH_LOOP_BACKOFF",
        "confidence": 0.96,
        "summary": "容器重复启动失败",
        "evidence_ids": ["ev-1"],
        "suggested_checks": ["读取previous logs"],
    }
]


class GoodProvider:
    def generate(self, messages: list[dict[str, str]]) -> ProviderOutput:
        assert "[REDACTED]" in messages[1]["content"]
        return ProviderOutput(
            payload={
                "incident_id": "inc-report",
                "summary": "容器启动后持续退出",
                "root_causes": [
                    {
                        "code": "CONTAINER_CRASH_LOOP_BACKOFF",
                        "description": "容器重复启动失败",
                        "confidence": 0.95,
                        "evidence_ids": ["ev-1"],
                    }
                ],
                "recommended_actions": [
                    {
                        "title": "检查日志",
                        "description": "读取previous logs定位退出原因",
                        "risk": "low",
                        "requires_approval": True,
                    }
                ],
                "unknowns": [],
            },
            model="mock-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )


class FailedProvider:
    def generate(self, messages: list[dict[str, str]]) -> ProviderOutput:
        raise RetryableDeepSeekError("simulated timeout")


def _patch_dependencies(monkeypatch, saved: dict[str, Any]) -> None:
    monkeypatch.setattr(report_service, "get_incident", lambda _: INCIDENT)
    monkeypatch.setattr(report_service, "list_evidence", lambda _: EVIDENCE)
    monkeypatch.setattr(
        report_service,
        "list_analysis_results",
        lambda _: RESULTS,
    )
    monkeypatch.setattr(
        report_service,
        "save_report",
        lambda report: saved.update(report.model_dump()) or saved,
    )
    monkeypatch.setattr(
        report_service,
        "transition_incident",
        lambda *args: None,
    )


def test_prompt_redacts_secret_and_marks_untrusted() -> None:
    messages = build_messages(INCIDENT, EVIDENCE, RESULTS)
    assert "secret-value" not in messages[1]["content"]
    assert "[REDACTED]" in messages[1]["content"]
    assert "不可信" in messages[0]["content"]


def test_valid_provider_report(monkeypatch) -> None:
    saved: dict[str, Any] = {}
    _patch_dependencies(monkeypatch, saved)
    report = report_service.generate_report("inc-report", GoodProvider())
    assert report["analysis_mode"] == "deepseek"
    assert report["model"] == "mock-model"
    assert report["total_tokens"] == 150


def test_provider_failure_uses_rules_fallback(monkeypatch) -> None:
    saved: dict[str, Any] = {}
    _patch_dependencies(monkeypatch, saved)
    report = report_service.generate_report("inc-report", FailedProvider())
    assert report["analysis_mode"] == "rules_fallback"
    assert report["root_causes"][0]["evidence_ids"] == ["ev-1"]
    assert "simulated timeout" in report["provider_error"]


def test_unknown_evidence_id_uses_fallback(monkeypatch) -> None:
    class HallucinatingProvider(GoodProvider):
        def generate(self, messages):
            output = super().generate(messages)
            output.payload["root_causes"][0]["evidence_ids"] = ["ev-fake"]
            return output

    saved: dict[str, Any] = {}
    _patch_dependencies(monkeypatch, saved)
    report = report_service.generate_report(
        "inc-report",
        HallucinatingProvider(),
    )
    assert report["analysis_mode"] == "rules_fallback"
    assert "unknown evidence ids" in report["provider_error"]
