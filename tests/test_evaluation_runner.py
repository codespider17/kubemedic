import json

import pytest

from app.evaluation_runner import (
    build_run_result,
    load_runner_config,
    select_run_incident,
)


def test_load_runner_config(tmp_path) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "namespace": "fault-lab",
                "workload_kind": "deployment",
                "workload_name": "crashloop-demo",
                "label_selector": "app=crashloop-demo",
                "container_name": "crashloop",
                "alert_name": "KubeMedicCrashLoopBackOff",
                "rule_namespace": "monitoring",
                "rule_name": "kubemedic-f01-crashloop",
            }
        ),
        encoding="utf-8",
    )

    result = load_runner_config(config_path)

    assert result["namespace"] == "fault-lab"
    assert result["workload_name"] == "crashloop-demo"
    assert result["alert_name"] == (
        "KubeMedicCrashLoopBackOff"
    )


def test_load_runner_config_rejects_missing_field(
    tmp_path,
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "namespace": "fault-lab",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="workload_kind",
    ):
        load_runner_config(config_path)


def test_select_run_incident_ignores_old_incident() -> None:
    items = [
        {
            "id": "inc-old",
            "status": "REPORTED",
            "alert_name": "KubeMedicCrashLoopBackOff",
            "namespace": "fault-lab",
            "last_seen": "2026-08-27T06:00:00+00:00",
        },
        {
            "id": "inc-current",
            "status": "REPORTED",
            "alert_name": "KubeMedicCrashLoopBackOff",
            "namespace": "fault-lab",
            "last_seen": "2026-08-27T07:00:10+00:00",
        },
    ]

    result = select_run_incident(
        items,
        alert_name="KubeMedicCrashLoopBackOff",
        namespace="fault-lab",
        run_started_at="2026-08-27T07:00:00+00:00",
    )

    assert result is not None
    assert result["id"] == "inc-current"


def test_select_run_incident_chooses_latest_candidate() -> None:
    items = [
        {
            "id": "inc-first",
            "status": "REPORTED",
            "alert_name": "KubeMedicCrashLoopBackOff",
            "namespace": "fault-lab",
            "last_seen": "2026-08-27T07:00:05+00:00",
        },
        {
            "id": "inc-latest",
            "status": "REPORTED",
            "alert_name": "KubeMedicCrashLoopBackOff",
            "namespace": "fault-lab",
            "last_seen": "2026-08-27T07:00:15+00:00",
        },
    ]

    result = select_run_incident(
        items,
        alert_name="KubeMedicCrashLoopBackOff",
        namespace="fault-lab",
        run_started_at="2026-08-27T07:00:00+00:00",
    )

    assert result is not None
    assert result["id"] == "inc-latest"


def test_select_run_incident_returns_none_without_match() -> None:
    result = select_run_incident(
        [],
        alert_name="KubeMedicCrashLoopBackOff",
        namespace="fault-lab",
        run_started_at="2026-08-27T07:00:00+00:00",
    )

    assert result is None


def test_build_run_result_passes_complete_run() -> None:
    result = build_run_result(
        run_id="F01-20260827T070000Z",
        scenario_id="F01",
        started_at="2026-08-27T07:00:00+00:00",
        finished_at="2026-08-27T07:05:00+00:00",
        incident_id="inc-current",
        phases=[
            {
                "name": "inject",
                "passed": True,
            },
            {
                "name": "recover",
                "passed": True,
            },
        ],
        evaluation={
            "passed": True,
        },
        error=None,
    )

    assert result["passed"] is True


def test_build_run_result_fails_incomplete_run() -> None:
    result = build_run_result(
        run_id="F01-20260827T070000Z",
        scenario_id="F01",
        started_at="2026-08-27T07:00:00+00:00",
        finished_at="2026-08-27T07:05:00+00:00",
        incident_id="inc-current",
        phases=[
            {
                "name": "inject",
                "passed": True,
            },
            {
                "name": "recover",
                "passed": False,
            },
        ],
        evaluation={
            "passed": True,
        },
        error=None,
    )

    assert result["passed"] is False
