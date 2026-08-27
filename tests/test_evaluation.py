from app.evaluation import build_evaluation


def make_expected() -> dict:
    return {
        "scenario_id": "F01",
        "scenario_name": "CrashLoopBackOff",
        "expected_alert_name": (
            "KubeMedicCrashLoopBackOff"
        ),
        "expected_namespace": "fault-lab",
        "expected_root_cause_code": (
            "CONTAINER_CRASH_LOOP_BACKOFF"
        ),
        "expected_evidence_sources": [
            "pod_status",
            "kubernetes_events",
            "pod_logs",
        ],
    }


def make_incident() -> dict:
    return {
        "id": "inc-test",
        "status": "RESOLVED",
        "alert_name": "KubeMedicCrashLoopBackOff",
        "namespace": "fault-lab",
        "first_seen": "2026-08-27T06:00:00+00:00",
        "events": [
            {
                "new_status": "RECEIVED",
                "created_at": (
                    "2026-08-27T06:00:00+00:00"
                ),
            },
            {
                "new_status": "REPORTED",
                "created_at": (
                    "2026-08-27T06:00:05+00:00"
                ),
            },
        ],
    }


def make_evidence() -> dict:
    return {
        "count": 3,
        "items": [
            {
                "source": "pod_status",
                "observed_at": (
                    "2026-08-27T06:00:01+00:00"
                ),
            },
            {
                "source": "kubernetes_events",
                "observed_at": (
                    "2026-08-27T06:00:02+00:00"
                ),
            },
            {
                "source": "pod_logs",
                "observed_at": (
                    "2026-08-27T06:00:03+00:00"
                ),
            },
        ],
    }


def make_analysis() -> dict:
    return {
        "items": [
            {
                "matched": True,
                "root_cause_code": (
                    "CONTAINER_CRASH_LOOP_BACKOFF"
                ),
                "confidence": 0.96,
            }
        ]
    }


def make_report() -> dict:
    return {
        "analysis_mode": "deepseek",
        "model": "deepseek-v4-flash",
        "created_at": "2026-08-27T06:00:05+00:00",
        "root_causes": [
            {
                "code": (
                    "CONTAINER_CRASH_LOOP_BACKOFF"
                )
            }
        ],
        "prompt_tokens": 4000,
        "completion_tokens": 500,
        "total_tokens": 4500,
        "provider_error": None,
    }


def test_successful_evaluation() -> None:
    result = build_evaluation(
        expected=make_expected(),
        incident=make_incident(),
        evidence=make_evidence(),
        analysis=make_analysis(),
        report=make_report(),
    )

    assert result["passed"] is True
    assert result["cycle_consistent"] is True
    assert result["top1_hit"] is True
    assert result["top3_hit"] is True
    assert result["evidence_complete"] is True
    assert result["incident_evidence_count"] == 3
    assert result["evidence_count"] == 3
    assert result["analysis_duration_ms"] == 5000
    assert result["total_tokens"] == 4500


def test_missing_evidence_fails_evaluation() -> None:
    evidence = make_evidence()
    evidence["items"] = [
        {
            "source": "pod_status",
            "observed_at": (
                "2026-08-27T06:00:01+00:00"
            ),
        }
    ]

    result = build_evaluation(
        expected=make_expected(),
        incident=make_incident(),
        evidence=evidence,
        analysis=make_analysis(),
        report=make_report(),
    )

    assert result["passed"] is False
    assert result["evidence_complete"] is False
    assert result["missing_evidence_sources"] == [
        "kubernetes_events",
        "pod_logs",
    ]


def test_analyzer_result_can_supply_root_cause() -> None:
    report = make_report()
    report["root_causes"] = []

    result = build_evaluation(
        expected=make_expected(),
        incident=make_incident(),
        evidence=make_evidence(),
        analysis=make_analysis(),
        report=report,
    )

    assert result["top1_hit"] is True
    assert result["predicted_root_cause_codes"] == [
        "CONTAINER_CRASH_LOOP_BACKOFF"
    ]


def test_latest_incident_cycle_is_evaluated() -> None:
    incident = make_incident()
    incident["events"] = [
        {
            "new_status": "RECEIVED",
            "created_at": (
                "2026-08-27T06:00:00+00:00"
            ),
        },
        {
            "new_status": "REPORTED",
            "created_at": (
                "2026-08-27T06:00:10+00:00"
            ),
        },
        {
            "new_status": "RESOLVED",
            "created_at": (
                "2026-08-27T06:01:00+00:00"
            ),
        },
        {
            "new_status": "RECEIVED",
            "created_at": (
                "2026-08-27T06:02:00+00:00"
            ),
        },
        {
            "new_status": "REPORTED",
            "created_at": (
                "2026-08-27T06:02:03+00:00"
            ),
        },
    ]

    evidence = {
        "count": 6,
        "items": [
            {
                "source": "pod_status",
                "observed_at": (
                    "2026-08-27T06:00:01+00:00"
                ),
            },
            {
                "source": "kubernetes_events",
                "observed_at": (
                    "2026-08-27T06:00:02+00:00"
                ),
            },
            {
                "source": "pod_logs",
                "observed_at": (
                    "2026-08-27T06:00:03+00:00"
                ),
            },
            {
                "source": "pod_status",
                "observed_at": (
                    "2026-08-27T06:02:01+00:00"
                ),
            },
            {
                "source": "kubernetes_events",
                "observed_at": (
                    "2026-08-27T06:02:01.500000+00:00"
                ),
            },
            {
                "source": "pod_logs",
                "observed_at": (
                    "2026-08-27T06:02:02+00:00"
                ),
            },
        ],
    }

    report = make_report()
    report["created_at"] = (
        "2026-08-27T06:02:03+00:00"
    )

    result = build_evaluation(
        expected=make_expected(),
        incident=incident,
        evidence=evidence,
        analysis=make_analysis(),
        report=report,
    )

    assert result["passed"] is True
    assert result["cycle_consistent"] is True
    assert result["incident_evidence_count"] == 6
    assert result["evidence_count"] == 3
    assert result["analysis_duration_ms"] == 3000
    assert result["cycle_started_at"] == (
        "2026-08-27T06:02:00+00:00"
    )
    assert result["cycle_reported_at"] == (
        "2026-08-27T06:02:03+00:00"
    )
