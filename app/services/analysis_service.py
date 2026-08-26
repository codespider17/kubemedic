from typing import Any

from app.analyzers.engine import run_analyzers
from app.domain.incident import IncidentStatus
from app.repositories.analysis_repository import (
    list_analysis_results,
    replace_analysis_results,
)
from app.repositories.evidence_repository import list_evidence
from app.services.incident_manager import get_incident


def analyze_incident(incident_id: str) -> list[dict[str, Any]]:
    incident = get_incident(incident_id)
    if incident is None:
        raise KeyError(incident_id)
    if incident["status"] != IncidentStatus.ANALYZING:
        raise ValueError(
            "incident must be ANALYZING before rule analysis, "
            f"got {incident['status']}"
        )

    evidence = list_evidence(incident_id)
    if not evidence:
        raise ValueError("incident has no evidence")

    results = run_analyzers(incident, evidence)
    return replace_analysis_results(incident_id, results)


def get_analysis(incident_id: str) -> list[dict[str, Any]]:
    incident = get_incident(incident_id)
    if incident is None:
        raise KeyError(incident_id)
    return list_analysis_results(incident_id)
