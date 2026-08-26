import json
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.report import AnalysisReport
from app.repositories.database import Base, get_session_factory


class ReportRecord(Base):
    __tablename__ = "reports"

    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    report_id: Mapped[str] = mapped_column(String(40), unique=True)
    analysis_mode: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    provider_error: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    report_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), index=True)


def save_report(report: AnalysisReport) -> dict[str, Any]:
    session_factory = get_session_factory()
    payload = report.model_dump(mode="json")
    with session_factory() as session:
        record = session.get(ReportRecord, report.incident_id)
        if record is None:
            record = ReportRecord(incident_id=report.incident_id)
            session.add(record)
        record.report_id = report.report_id
        record.analysis_mode = report.analysis_mode
        record.provider = report.provider
        record.model = report.model
        record.provider_error = report.provider_error
        record.report_json = json.dumps(payload, ensure_ascii=False)
        record.created_at = report.created_at
        session.commit()
    return payload


def get_report(incident_id: str) -> dict[str, Any] | None:
    session_factory = get_session_factory()
    with session_factory() as session:
        record = session.get(ReportRecord, incident_id)
        if record is None:
            return None
        return json.loads(record.report_json)
