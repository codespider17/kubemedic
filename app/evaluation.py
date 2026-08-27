from datetime import UTC, datetime
from typing import Any


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _latest_cycle_bounds(
    incident: dict[str, Any],
) -> tuple[datetime | None, datetime | None]:
    events = sorted(
        incident.get("events", []),
        key=lambda event: event.get("created_at", ""),
    )

    received_times = [
        _parse_time(event["created_at"])
        for event in events
        if event.get("new_status") == "RECEIVED"
        and event.get("created_at")
    ]

    if not received_times:
        first_seen = incident.get("first_seen")
        if first_seen is None:
            return None, None
        cycle_start = _parse_time(first_seen)
    else:
        cycle_start = received_times[-1]

    reported_times = [
        _parse_time(event["created_at"])
        for event in events
        if event.get("new_status") == "REPORTED"
        and event.get("created_at")
        and _parse_time(event["created_at"]) >= cycle_start
    ]

    cycle_reported = (
        reported_times[0]
        if reported_times
        else None
    )
    return cycle_start, cycle_reported


def _evidence_for_cycle(
    evidence: dict[str, Any],
    cycle_start: datetime | None,
    cycle_reported: datetime | None,
) -> list[dict[str, Any]]:
    items = evidence.get("items", [])

    if cycle_start is None or cycle_reported is None:
        return items

    selected: list[dict[str, Any]] = []
    for item in items:
        observed_at = item.get("observed_at")
        if observed_at is None:
            continue

        observed_time = _parse_time(observed_at)
        if cycle_start <= observed_time <= cycle_reported:
            selected.append(item)

    return selected


def _predicted_root_causes(
    analysis: dict[str, Any],
    report: dict[str, Any],
) -> list[str]:
    report_codes = [
        item.get("code", "")
        for item in report.get("root_causes", [])
    ]

    matched_analysis = sorted(
        (
            item
            for item in analysis.get("items", [])
            if item.get("matched") is True
        ),
        key=lambda item: item.get("confidence", 0.0),
        reverse=True,
    )
    analyzer_codes = [
        item.get("root_cause_code", "")
        for item in matched_analysis
    ]

    return _unique(report_codes + analyzer_codes)


def _duration_ms(
    cycle_start: datetime | None,
    cycle_reported: datetime | None,
) -> int | None:
    if cycle_start is None or cycle_reported is None:
        return None

    duration = cycle_reported - cycle_start
    return max(
        0,
        round(duration.total_seconds() * 1000),
    )


def _report_matches_cycle(
    report: dict[str, Any],
    cycle_start: datetime | None,
) -> bool:
    created_at = report.get("created_at")
    if created_at is None or cycle_start is None:
        return False

    return _parse_time(created_at) >= cycle_start


def build_evaluation(
    expected: dict[str, Any],
    incident: dict[str, Any],
    evidence: dict[str, Any],
    analysis: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    cycle_start, cycle_reported = (
        _latest_cycle_bounds(incident)
    )
    cycle_evidence = _evidence_for_cycle(
        evidence,
        cycle_start,
        cycle_reported,
    )

    expected_code = expected["expected_root_cause_code"]
    predicted_codes = _predicted_root_causes(
        analysis,
        report,
    )

    required_sources = sorted(
        set(expected.get("expected_evidence_sources", []))
    )
    actual_sources = sorted(
        {
            item.get("source", "")
            for item in cycle_evidence
            if item.get("source")
        }
    )
    missing_sources = sorted(
        set(required_sources) - set(actual_sources)
    )

    alert_detected = (
        incident.get("alert_name")
        == expected.get("expected_alert_name")
    )
    namespace_matches = (
        incident.get("namespace")
        == expected.get("expected_namespace")
    )
    top1_hit = bool(
        predicted_codes
        and predicted_codes[0] == expected_code
    )
    top3_hit = expected_code in predicted_codes[:3]
    evidence_complete = not missing_sources
    recovered = incident.get("status") == "RESOLVED"
    cycle_consistent = _report_matches_cycle(
        report,
        cycle_start,
    )

    passed = all(
        (
            alert_detected,
            namespace_matches,
            top1_hit,
            evidence_complete,
            recovered,
            cycle_consistent,
        )
    )

    return {
        "scenario_id": expected["scenario_id"],
        "scenario_name": expected.get("scenario_name"),
        "incident_id": incident.get("id"),
        "evaluated_at": datetime.now(UTC).isoformat(),
        "cycle_started_at": (
            cycle_start.isoformat()
            if cycle_start is not None
            else None
        ),
        "cycle_reported_at": (
            cycle_reported.isoformat()
            if cycle_reported is not None
            else None
        ),
        "cycle_consistent": cycle_consistent,
        "alert_detected": alert_detected,
        "namespace_matches": namespace_matches,
        "expected_root_cause_code": expected_code,
        "predicted_root_cause_codes": predicted_codes,
        "top1_hit": top1_hit,
        "top3_hit": top3_hit,
        "required_evidence_sources": required_sources,
        "actual_evidence_sources": actual_sources,
        "missing_evidence_sources": missing_sources,
        "evidence_complete": evidence_complete,
        "incident_evidence_count": evidence.get(
            "count",
            len(evidence.get("items", [])),
        ),
        "evidence_count": len(cycle_evidence),
        "analysis_duration_ms": _duration_ms(
            cycle_start,
            cycle_reported,
        ),
        "report_created_at": report.get("created_at"),
        "analysis_mode": report.get("analysis_mode"),
        "model": report.get("model"),
        "prompt_tokens": report.get("prompt_tokens"),
        "completion_tokens": report.get(
            "completion_tokens"
        ),
        "total_tokens": report.get("total_tokens"),
        "provider_error": report.get("provider_error"),
        "tool_calls": None,
        "unsafe_calls_rejected": None,
        "recovered": recovered,
        "passed": passed,
    }
