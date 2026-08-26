import json
from typing import Any

from sqlalchemy import ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.evidence import Evidence
from app.repositories.database import Base, get_session_factory


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
    )
    source: Mapped[str] = mapped_column(String(80), index=True)
    resource_ref: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(String(1000))
    observed_at: Mapped[str] = mapped_column(String(40), index=True)
    raw_json: Mapped[str] = mapped_column(Text)
    sensitivity: Mapped[str] = mapped_column(String(20))


def save_evidence(evidence: Evidence) -> dict[str, Any]:
    session_factory = get_session_factory()
    with session_factory() as session:
        record = EvidenceRecord(
            evidence_id=evidence.evidence_id,
            incident_id=evidence.incident_id,
            source=evidence.source,
            resource_ref=evidence.resource_ref,
            summary=evidence.summary,
            observed_at=evidence.observed_at,
            raw_json=json.dumps(
                evidence.raw,
                ensure_ascii=False,
                sort_keys=True,
            ),
            sensitivity=evidence.sensitivity,
        )
        session.add(record)
        session.commit()
    return evidence.model_dump(mode="json")


def list_evidence(incident_id: str) -> list[dict[str, Any]]:
    session_factory = get_session_factory()
    with session_factory() as session:
        records = session.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.incident_id == incident_id)
            .order_by(EvidenceRecord.observed_at.asc())
        ).all()
        return [
            {
                "evidence_id": record.evidence_id,
                "incident_id": record.incident_id,
                "source": record.source,
                "resource_ref": record.resource_ref,
                "summary": record.summary,
                "observed_at": record.observed_at,
                "raw": json.loads(record.raw_json),
                "sensitivity": record.sensitivity,
            }
            for record in records
        ]
