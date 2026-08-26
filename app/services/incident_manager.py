import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from app.domain.incident import IncidentStatus, validate_transition
from app.repositories.database import (
    AlertRecord,
    IncidentEventRecord,
    IncidentRecord,
    get_session_factory,
    utc_now_iso,
)

DEFAULT_DEDUP_WINDOW_SECONDS = 600
WORKLOAD_LABELS = ("deployment", "statefulset", "daemonset", "job")


def build_fingerprint(labels: dict[str, str]) -> str:
    workload = next(
        (labels[key] for key in WORKLOAD_LABELS if labels.get(key)),
        labels.get("pod", "unknown"),
    )
    canonical = {
        "cluster_id": os.getenv("KUBEMEDIC_CLUSTER_ID", "k3s-local"),
        "alertname": labels.get("alertname", "unknown"),
        "namespace": labels.get("namespace", "default"),
        "workload": workload,
        "pod": labels.get("pod", "unknown"),
        "container": labels.get("container", "unknown"),
    }
    encoded = json.dumps(canonical, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_dict(record: IncidentRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "fingerprint": record.fingerprint,
        "status": record.status,
        "alert_name": record.alert_name,
        "namespace": record.namespace,
        "workload": record.workload,
        "pod": record.pod,
        "severity": record.severity,
        "occurrence_count": record.occurrence_count,
        "first_seen": record.first_seen,
        "last_seen": record.last_seen,
        "resolved_at": record.resolved_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _add_event(
    session,
    incident_id: str,
    old_status: str | None,
    new_status: str,
    reason: str,
    created_at: str,
) -> None:
    session.add(
        IncidentEventRecord(
            id=f"evt-{uuid4().hex}",
            incident_id=incident_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            created_at=created_at,
        )
    )


def _seconds_since(timestamp: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(timestamp)).total_seconds()


def process_alertmanager_payload(payload: dict[str, Any]) -> dict[str, Any]:
    session_factory = get_session_factory()
    incident_ids: list[str] = []
    summaries: list[dict[str, Any]] = []
    now_datetime = datetime.now(UTC)
    now = now_datetime.isoformat()
    dedup_window = int(
        os.getenv(
            "INCIDENT_DEDUP_WINDOW_SECONDS",
            str(DEFAULT_DEDUP_WINDOW_SECONDS),
        )
    )

    with session_factory() as session:
        for alert in payload.get("alerts", []):
            labels = alert.get("labels") or {}
            alert_status = alert.get("status", payload.get("status", "firing"))
            fingerprint = build_fingerprint(labels)

            latest = session.scalar(
                select(IncidentRecord)
                .where(IncidentRecord.fingerprint == fingerprint)
                .order_by(IncidentRecord.last_seen.desc())
                .limit(1)
            )

            record = latest
            created = False

            if alert_status == "firing":
                should_create = latest is None
                if latest is not None and latest.status == IncidentStatus.RESOLVED:
                    should_create = (
                        _seconds_since(latest.last_seen, now_datetime) > dedup_window
                    )

                if should_create:
                    workload = next(
                        (labels[key] for key in WORKLOAD_LABELS if labels.get(key)),
                        labels.get("pod", "unknown"),
                    )
                    record = IncidentRecord(
                        id=f"inc-{uuid4().hex[:16]}",
                        fingerprint=fingerprint,
                        status=IncidentStatus.RECEIVED,
                        alert_name=labels.get("alertname", "unknown"),
                        namespace=labels.get("namespace", "default"),
                        workload=workload,
                        pod=labels.get("pod", "unknown"),
                        severity=labels.get("severity", "unknown"),
                        occurrence_count=1,
                        first_seen=now,
                        last_seen=now,
                        resolved_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(record)
                    _add_event(
                        session,
                        record.id,
                        None,
                        IncidentStatus.RECEIVED,
                        "first firing alert received",
                        now,
                    )
                    created = True
                else:
                    if record is None:
                        raise RuntimeError("incident lookup returned no record")
                    old_status = record.status
                    if old_status == IncidentStatus.RESOLVED:
                        validate_transition(
                            IncidentStatus(old_status),
                            IncidentStatus.RECEIVED,
                        )
                        record.status = IncidentStatus.RECEIVED
                        record.resolved_at = None
                        _add_event(
                            session,
                            record.id,
                            old_status,
                            IncidentStatus.RECEIVED,
                            "firing alert reopened incident inside dedup window",
                            now,
                        )
                    record.occurrence_count += 1
                    record.last_seen = now
                    record.updated_at = now
            else:
                if record is None:
                    continue
                old_status = record.status
                if old_status != IncidentStatus.RESOLVED:
                    validate_transition(
                        IncidentStatus(old_status),
                        IncidentStatus.RESOLVED,
                    )
                    record.status = IncidentStatus.RESOLVED
                    record.resolved_at = now
                    record.updated_at = now
                    record.last_seen = now
                    record.occurrence_count += 1
                    _add_event(
                        session,
                        record.id,
                        old_status,
                        IncidentStatus.RESOLVED,
                        "resolved alert received",
                        now,
                    )

            if record is None:
                continue

            session.add(
                AlertRecord(
                    id=f"alt-{uuid4().hex}",
                    incident_id=record.id,
                    status=alert_status,
                    payload_json=json.dumps(
                        alert,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    received_at=now,
                )
            )

            if record.id not in incident_ids:
                incident_ids.append(record.id)
            summaries.append(
                {
                    "incident_id": record.id,
                    "created": created,
                    "status": record.status,
                    "alertname": record.alert_name,
                    "namespace": record.namespace,
                    "pod": record.pod,
                    "severity": record.severity,
                    "fingerprint": fingerprint,
                }
            )

        session.commit()

    return {
        "accepted": len(payload.get("alerts", [])),
        "incident_ids": incident_ids,
        "alerts": summaries,
    }


def transition_incident(
    incident_id: str,
    target: IncidentStatus,
    reason: str,
) -> dict[str, Any]:
    session_factory = get_session_factory()
    now = utc_now_iso()

    with session_factory() as session:
        record = session.get(IncidentRecord, incident_id)
        if record is None:
            raise KeyError(incident_id)

        current = IncidentStatus(record.status)
        validate_transition(current, target)
        if current == target:
            return _as_dict(record)

        record.status = target
        record.updated_at = now
        if target == IncidentStatus.RESOLVED:
            record.resolved_at = now
        _add_event(
            session,
            record.id,
            current,
            target,
            reason,
            now,
        )
        session.commit()
        return _as_dict(record)


def list_incidents(limit: int = 50) -> list[dict[str, Any]]:
    session_factory = get_session_factory()
    with session_factory() as session:
        records = session.scalars(
            select(IncidentRecord)
            .order_by(IncidentRecord.last_seen.desc())
            .limit(limit)
        ).all()
        return [_as_dict(record) for record in records]


def get_incident(incident_id: str) -> dict[str, Any] | None:
    session_factory = get_session_factory()
    with session_factory() as session:
        record = session.get(IncidentRecord, incident_id)
        if record is None:
            return None

        result = _as_dict(record)
        result["alert_count"] = session.scalar(
            select(func.count(AlertRecord.id)).where(
                AlertRecord.incident_id == incident_id
            )
        )
        events = session.scalars(
            select(IncidentEventRecord)
            .where(IncidentEventRecord.incident_id == incident_id)
            .order_by(IncidentEventRecord.created_at.asc())
        ).all()
        result["events"] = [
            {
                "id": event.id,
                "old_status": event.old_status,
                "new_status": event.new_status,
                "reason": event.reason,
                "created_at": event.created_at,
            }
            for event in events
        ]
        return result
