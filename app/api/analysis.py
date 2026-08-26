from fastapi import APIRouter, HTTPException

from app.services.analysis_service import analyze_incident, get_analysis

router = APIRouter()


def _response(items: list[dict]) -> dict[str, object]:
    matched = [item for item in items if item["matched"]]
    return {
        "count": len(items),
        "matched_count": len(matched),
        "primary": matched[0] if matched else None,
        "items": items,
    }


@router.post("/incidents/{incident_id}/analyze")
def run_analysis(incident_id: str) -> dict[str, object]:
    try:
        items = analyze_incident(incident_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail="incident not found",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _response(items)


@router.get("/incidents/{incident_id}/analysis")
def find_analysis(incident_id: str) -> dict[str, object]:
    try:
        items = get_analysis(incident_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail="incident not found",
        ) from error
    return _response(items)
