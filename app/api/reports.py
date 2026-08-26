from fastapi import APIRouter, HTTPException

from app.services.report_service import find_report, generate_report

router = APIRouter()


@router.post("/incidents/{incident_id}/report")
def create_report(incident_id: str) -> dict:
    try:
        return generate_report(incident_id)
    except KeyError as error:
        raise HTTPException(404, "incident not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/incidents/{incident_id}/report")
def read_report(incident_id: str) -> dict:
    try:
        report = find_report(incident_id)
    except KeyError as error:
        raise HTTPException(404, "incident not found") from error
    if report is None:
        raise HTTPException(404, "report not found")
    return report
