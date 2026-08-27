import json
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_RUNNER_KEYS = (
    "namespace",
    "workload_kind",
    "workload_name",
    "label_selector",
    "container_name",
    "alert_name",
    "rule_namespace",
    "rule_name",
)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_runner_config(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as file:
        raw_config = json.load(file)

    if not isinstance(raw_config, dict):
        raise TypeError("runner config must be a JSON object")

    config: dict[str, str] = {}

    for key in REQUIRED_RUNNER_KEYS:
        value = raw_config.get(key)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"runner config field must be a non-empty string: {key}"
            )

        config[key] = value.strip()

    return config


def select_run_incident(
    items: list[dict[str, Any]],
    *,
    alert_name: str,
    namespace: str,
    run_started_at: str,
    accepted_statuses: tuple[str, ...] = (
        "REPORTED",
        "RESOLVED",
    ),
) -> dict[str, Any] | None:
    run_started = parse_time(run_started_at)
    candidates: list[dict[str, Any]] = []

    for item in items:
        if item.get("alert_name") != alert_name:
            continue

        if item.get("namespace") != namespace:
            continue

        if item.get("status") not in accepted_statuses:
            continue

        last_seen = item.get("last_seen")
        if not isinstance(last_seen, str):
            continue

        try:
            last_seen_time = parse_time(last_seen)
        except ValueError:
            continue

        if last_seen_time < run_started:
            continue

        candidates.append(item)

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: parse_time(item["last_seen"]),
    )


def build_run_result(
    *,
    run_id: str,
    scenario_id: str,
    started_at: str,
    finished_at: str,
    incident_id: str | None,
    phases: list[dict[str, Any]],
    evaluation: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    phase_success = all(
        phase.get("passed") is True
        for phase in phases
    )

    evaluation_success = (
        evaluation is not None
        and evaluation.get("passed") is True
    )

    passed = (
        phase_success
        and evaluation_success
        and error is None
    )

    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "incident_id": incident_id,
        "phases": phases,
        "evaluation": evaluation,
        "error": error,
        "passed": passed,
    }
