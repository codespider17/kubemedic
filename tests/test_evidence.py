from types import SimpleNamespace

import pytest

from app.collectors import kubernetes_collector
from app.collectors.prometheus_collector import build_query
from app.domain.evidence import Evidence, redact_sensitive_text
from app.services import evidence_service


def test_redact_sensitive_text() -> None:
    text = "token=abc password=xyz Authorization: Bearer secret-value"
    redacted = redact_sensitive_text(text)
    assert "abc" not in redacted
    assert "xyz" not in redacted
    assert "secret-value" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_prometheus_query_templates_reject_unknown_id() -> None:
    query = build_query(
        "pod_restart_increase",
        {"namespace": "demo", "pod": "demo-pod"},
    )
    assert "kube_pod_container_status_restarts_total" in query
    with pytest.raises(ValueError):
        build_query(
            "arbitrary_promql",
            {"namespace": "demo", "pod": "demo-pod"},
        )


def test_get_pod_status_with_mock_client(monkeypatch) -> None:
    container_status = SimpleNamespace(
        name="api",
        ready=False,
        restart_count=3,
        state=SimpleNamespace(
            waiting=SimpleNamespace(
                reason="CrashLoopBackOff",
                message="back-off",
            ),
            running=None,
            terminated=None,
        ),
        last_state=SimpleNamespace(
            waiting=None,
            running=None,
            terminated=SimpleNamespace(
                reason="Error",
                message=None,
                exit_code=1,
                signal=0,
                started_at=None,
                finished_at=None,
            ),
        ),
    )
    pod = SimpleNamespace(
        status=SimpleNamespace(
            phase="Running",
            pod_ip="10.42.0.10",
            container_statuses=[container_status],
            conditions=[],
        ),
        spec=SimpleNamespace(node_name="k8s-m1"),
    )
    fake_core = SimpleNamespace(
        read_namespaced_pod=lambda name, namespace: pod
    )
    fake_clients = SimpleNamespace(core=fake_core)
    monkeypatch.setattr(
        kubernetes_collector,
        "get_kubernetes_clients",
        lambda: fake_clients,
    )

    evidence = kubernetes_collector.get_pod_status(
        "inc-test",
        "demo",
        "demo-pod",
    )
    assert evidence.source == "pod_status"
    assert evidence.raw["containers"][0]["restart_count"] == 3
    assert "restarts=3" in evidence.summary


def test_collect_endpoint_persists_mocked_evidence(client, monkeypatch) -> None:
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "EvidenceTest",
                    "namespace": "demo",
                    "pod": "evidence-pod",
                    "severity": "warning",
                },
                "annotations": {},
            }
        ],
    }
    incident_id = client.post(
        "/api/v1/alerts/webhook",
        json=payload,
    ).json()["incident_ids"][0]

    def fake_evidence(source: str) -> Evidence:
        raw = {"containers": [{"name": "api"}]} if source == "pod_status" else {}
        return Evidence(
            incident_id=incident_id,
            source=source,
            resource_ref="demo/Pod/evidence-pod",
            summary=f"mock {source}",
            raw=raw,
        )

    monkeypatch.setattr(
        evidence_service,
        "get_pod_status",
        lambda *args, **kwargs: fake_evidence("pod_status"),
    )
    monkeypatch.setattr(
        evidence_service,
        "get_owner_chain",
        lambda *args, **kwargs: fake_evidence("owner_chain"),
    )
    monkeypatch.setattr(
        evidence_service,
        "get_events",
        lambda *args, **kwargs: fake_evidence("kubernetes_events"),
    )
    monkeypatch.setattr(
        evidence_service,
        "get_pod_logs",
        lambda *args, **kwargs: fake_evidence("pod_logs"),
    )
    monkeypatch.setattr(
        evidence_service,
        "query_prometheus",
        lambda incident_id, query_id, labels: fake_evidence(query_id),
    )

    response = client.post(f"/api/v1/incidents/{incident_id}/collect")
    assert response.status_code == 200
    assert response.json()["count"] == 6

    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "ANALYZING"

    stored = client.get(
        f"/api/v1/incidents/{incident_id}/evidence"
    ).json()
    assert stored["count"] == 6
