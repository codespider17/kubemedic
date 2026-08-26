import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.domain.incident import IncidentStatus
from app.services.incident_manager import process_alertmanager_payload
from app.services.pipeline_service import process_incident_pipeline

router = APIRouter()


class Alert(BaseModel):
    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime | None = None
    endsAt: datetime | None = None
    generatorURL: str | None = None
    fingerprint: str | None = None


class AlertmanagerPayload(BaseModel):
    version: str | None = None
    groupKey: str | None = None
    truncatedAlerts: int = 0
    status: str
    receiver: str | None = None
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[Alert] = Field(default_factory=list)


def _auto_pipeline_enabled() -> bool:
    return os.getenv("KUBEMEDIC_AUTO_PIPELINE", "false").lower() in {
        "1",
        "true",
        "yes",
    }


@router.post("/webhook")
def receive_alerts(
    payload: AlertmanagerPayload,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    normalized = payload.model_dump(mode="json")
    result = process_alertmanager_payload(normalized)
    if _auto_pipeline_enabled():
        for item in result["alerts"]:
            if item["status"] == IncidentStatus.RECEIVED:
                background_tasks.add_task(
                    process_incident_pipeline,
                    item["incident_id"],
                )
    return result
