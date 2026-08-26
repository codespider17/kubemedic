from typing import Any

import pytest

from app.analyzers.engine import primary_result, run_analyzers
from app.analyzers.rules import ANALYZERS

INCIDENT = {
    "id": "inc-test",
    "status": "ANALYZING",
    "namespace": "demo",
    "pod": "demo-pod",
}


def evidence(
    source: str,
    raw: dict[str, Any],
    number: int = 1,
) -> dict[str, Any]:
    return {
        "evidence_id": f"ev-{number}",
        "incident_id": "inc-test",
        "source": source,
        "resource_ref": "demo/Pod/demo-pod",
        "summary": source,
        "observed_at": "2026-08-26T12:00:00+00:00",
        "raw": raw,
        "sensitivity": "normal",
    }


def find_result(name: str, items: list[dict[str, Any]]):
    _, analyzer = next(item for item in ANALYZERS if item[0] == name)
    return analyzer(INCIDENT, items)


def test_oom_killed_matches_second_container() -> None:
    item = evidence(
        "pod_status",
        {
            "phase": "Running",
            "containers": [
                {
                    "name": "sidecar",
                    "state": {"type": "running"},
                    "last_state": None,
                },
                {
                    "name": "api",
                    "state": {"type": "waiting"},
                    "last_state": {
                        "type": "terminated",
                        "reason": "OOMKilled",
                        "exit_code": "137",
                    },
                },
            ],
        },
    )
    result = find_result("oom_killed", [item])
    assert result.matched is True
    assert result.root_cause_code == "CONTAINER_OOM_KILLED"
    assert result.evidence_ids == ["ev-1"]


def test_crash_loop_matches_waiting_reason() -> None:
    item = evidence(
        "pod_status",
        {
            "containers": [
                {
                    "name": "api",
                    "restart_count": 6,
                    "state": {
                        "type": "waiting",
                        "reason": "CrashLoopBackOff",
                    },
                }
            ]
        },
    )
    result = find_result("crash_loop_backoff", [item])
    assert result.matched is True
    assert result.confidence == pytest.approx(0.96)


def test_image_pull_matches_event() -> None:
    item = evidence(
        "kubernetes_events",
        {
            "items": [
                {
                    "reason": "Failed",
                    "message": "Failed to pull image example.invalid/app:v1",
                }
            ]
        },
    )
    result = find_result("image_pull", [item])
    assert result.matched is True
    assert result.root_cause_code == "IMAGE_PULL_FAILED"


def test_probe_failure_requires_probe_event() -> None:
    status = evidence(
        "pod_status",
        {"conditions": [{"type": "Ready", "status": "False"}]},
    )
    result = find_result("probe_failure", [status])
    assert result.matched is False

    event = evidence(
        "kubernetes_events",
        {
            "items": [
                {
                    "reason": "Unhealthy",
                    "message": "Readiness probe failed: connection refused",
                }
            ]
        },
        number=2,
    )
    result = find_result("probe_failure", [status, event])
    assert result.matched is True
    assert result.facts["ready_false"] is True


def test_pending_requires_failed_scheduling() -> None:
    status = evidence("pod_status", {"phase": "Pending"})
    weak_result = find_result("pending_scheduling", [status])
    assert weak_result.matched is False
    assert weak_result.confidence == pytest.approx(0.30)

    event = evidence(
        "kubernetes_events",
        {
            "items": [
                {
                    "reason": "FailedScheduling",
                    "message": "0/1 nodes are available: Insufficient memory",
                }
            ]
        },
        number=2,
    )
    result = find_result("pending_scheduling", [status, event])
    assert result.matched is True


def test_service_no_endpoints_positive_and_negative() -> None:
    broken = evidence(
        "service_endpoints",
        {
            "selector": {"app": "api"},
            "ports": [{"port": 80, "target_port": "http"}],
            "endpoints": [],
        },
    )
    healthy = evidence(
        "service_endpoints",
        {
            "selector": {"app": "api"},
            "ports": [{"port": 80, "target_port": "http"}],
            "endpoints": [
                {
                    "addresses": ["10.42.0.10"],
                    "ready": True,
                    "target_name": "api-123",
                }
            ],
        },
        number=2,
    )
    assert find_result("service_no_endpoints", [broken]).matched is True
    assert find_result("service_no_endpoints", [healthy]).matched is False


def test_missing_and_malformed_evidence_never_raises() -> None:
    malformed = evidence("pod_status", {"containers": None})
    results = run_analyzers(INCIDENT, [malformed])
    assert len(results) == 6
    assert all(result.matched is False for result in results)


def test_engine_places_highest_confidence_match_first() -> None:
    item = evidence(
        "pod_status",
        {
            "containers": [
                {
                    "name": "api",
                    "state": {
                        "type": "waiting",
                        "reason": "CrashLoopBackOff",
                    },
                    "last_state": {
                        "type": "terminated",
                        "reason": "OOMKilled",
                        "exit_code": "137",
                    },
                }
            ]
        },
    )
    results = run_analyzers(INCIDENT, [item])
    assert results[0].root_cause_code == "CONTAINER_OOM_KILLED"
    assert primary_result(results) == results[0]
