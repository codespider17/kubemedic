from copy import deepcopy

import pytest

from app.domain.incident import (
    IncidentStatus,
    InvalidIncidentTransition,
)
from app.services.incident_manager import transition_incident


def make_payload(pod: str, alertname: str) -> dict:
    return {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alertname,
                    "namespace": "demo",
                    "pod": pod,
                    "severity": "warning",
                },
                "annotations": {"summary": "test incident"},
            }
        ],
    }


def test_duplicate_alerts_reuse_incident(client) -> None:
    payload = make_payload("dedup-pod", "DedupTest")
    responses = [
        client.post("/api/v1/alerts/webhook", json=payload).json()
        for _ in range(3)
    ]

    incident_ids = {response["incident_ids"][0] for response in responses}
    assert len(incident_ids) == 1

    incident_id = responses[0]["incident_ids"][0]
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["occurrence_count"] == 3
    assert detail["alert_count"] == 3


def test_different_pods_create_different_incidents(client) -> None:
    first = client.post(
        "/api/v1/alerts/webhook",
        json=make_payload("pod-a", "DifferentPodTest"),
    ).json()
    second = client.post(
        "/api/v1/alerts/webhook",
        json=make_payload("pod-b", "DifferentPodTest"),
    ).json()

    assert first["incident_ids"][0] != second["incident_ids"][0]


def test_resolved_alert_closes_existing_incident(client) -> None:
    firing = make_payload("resolved-pod", "ResolvedTest")
    created = client.post(
        "/api/v1/alerts/webhook",
        json=firing,
    ).json()
    incident_id = created["incident_ids"][0]

    resolved = deepcopy(firing)
    resolved["status"] = "resolved"
    resolved["alerts"][0]["status"] = "resolved"
    closed = client.post(
        "/api/v1/alerts/webhook",
        json=resolved,
    ).json()

    assert closed["incident_ids"][0] == incident_id
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "RESOLVED"
    assert detail["resolved_at"] is not None


def test_state_machine_accepts_and_rejects_transitions(client) -> None:
    created = client.post(
        "/api/v1/alerts/webhook",
        json=make_payload("state-pod", "StateMachineTest"),
    ).json()
    incident_id = created["incident_ids"][0]

    collecting = transition_incident(
        incident_id,
        IncidentStatus.COLLECTING,
        "test collector started",
    )
    assert collecting["status"] == "COLLECTING"

    analyzing = transition_incident(
        incident_id,
        IncidentStatus.ANALYZING,
        "test analysis started",
    )
    assert analyzing["status"] == "ANALYZING"

    with pytest.raises(InvalidIncidentTransition):
        transition_incident(
            incident_id,
            IncidentStatus.RECEIVED,
            "invalid backward transition",
        )
def test_explicit_workload_label_is_preferred(client) -> None:
    payload = make_payload(
        "workload-label-pod",
        "ExplicitWorkloadLabelTest",
    )
    labels = payload["alerts"][0]["labels"]
    labels.update(
        {
            "workload": "crashloop-demo",
            "workload_kind": "Deployment",
            "job": "kube-state-metrics",
        }
    )

    response = client.post(
        "/api/v1/alerts/webhook",
        json=payload,
    )
    assert response.status_code == 200

    incident_id = response.json()["incident_ids"][0]
    detail = client.get(
        f"/api/v1/incidents/{incident_id}"
    ).json()

    assert detail["workload"] == "crashloop-demo"
    assert detail["pod"] == "workload-label-pod"


def test_prometheus_job_label_is_not_workload(client) -> None:
    payload = make_payload(
        "prometheus-job-pod",
        "PrometheusJobLabelTest",
    )
    payload["alerts"][0]["labels"]["job"] = (
        "kube-state-metrics"
    )

    response = client.post(
        "/api/v1/alerts/webhook",
        json=payload,
    )
    assert response.status_code == 200

    incident_id = response.json()["incident_ids"][0]
    detail = client.get(
        f"/api/v1/incidents/{incident_id}"
    ).json()

    assert detail["workload"] == "prometheus-job-pod"
    assert detail["workload"] != "kube-state-metrics"
