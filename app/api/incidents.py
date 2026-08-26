from fastapi import APIRouter, HTTPException, Query

from app.services.incident_manager import get_incident, list_incidents

router = APIRouter()


@router.get("")
def find_incidents(
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    items = list_incidents(limit=limit)
    return {"count": len(items), "items": items}


@router.get("/{incident_id}")
def find_incident(incident_id: str) -> dict[str, object]:
    incident = get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident
