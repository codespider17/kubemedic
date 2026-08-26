from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.incident_manager import process_alertmanager_payload

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


@router.post("/webhook")
def receive_alerts(payload: AlertmanagerPayload) -> dict[str, object]:
    normalized = payload.model_dump(mode="json")
    return process_alertmanager_payload(normalized)
