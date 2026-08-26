import logging

from app.domain.incident import IncidentStatus
from app.repositories.analysis_repository import list_analysis_results
from app.services.analysis_service import analyze_incident
from app.services.evidence_service import collect_incident_evidence
from app.services.incident_manager import get_incident
from app.services.report_service import generate_report

LOGGER = logging.getLogger(__name__)
PIPELINE_EXCEPTIONS = (KeyError, ValueError, RuntimeError)


def process_incident_pipeline(incident_id: str) -> None:
    try:
        incident = get_incident(incident_id)
        if incident is None:
            raise KeyError(incident_id)

        if incident["status"] == IncidentStatus.RECEIVED:
            collect_incident_evidence(incident_id)
            incident = get_incident(incident_id)

        if (
            incident is not None
            and incident["status"] == IncidentStatus.ANALYZING
        ):
            if not list_analysis_results(incident_id):
                analyze_incident(incident_id)
            generate_report(incident_id)
    except PIPELINE_EXCEPTIONS:
        LOGGER.exception("incident pipeline failed incident_id=%s", incident_id)
