from fastapi import APIRouter, HTTPException

from app.repositories.evidence_repository import list_evidence
from app.services.evidence_service import collect_incident_evidence

router = APIRouter()


@router.post("/incidents/{incident_id}/collect")
def collect(incident_id: str) -> dict[str, object]:
    try:
        items = collect_incident_evidence(incident_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail="incident not found",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"count": len(items), "items": items}


@router.get("/incidents/{incident_id}/evidence")
def find_evidence(incident_id: str) -> dict[str, object]:
    items = list_evidence(incident_id)
    return {"count": len(items), "items": items}
