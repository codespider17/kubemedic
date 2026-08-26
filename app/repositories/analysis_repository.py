import json
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.analysis import AnalyzerResult
from app.repositories.database import Base, get_session_factory


class AnalysisResultRecord(Base):
    __tablename__ = "analysis_results"

    result_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
    )
    analyzer: Mapped[str] = mapped_column(String(80), index=True)
    matched: Mapped[bool] = mapped_column(Boolean, index=True)
    root_cause_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(String(1000))
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    suggested_checks_json: Mapped[str] = mapped_column(Text)
    facts_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), index=True)


def _as_dict(record: AnalysisResultRecord) -> dict[str, Any]:
    return {
        "result_id": record.result_id,
        "incident_id": record.incident_id,
        "analyzer": record.analyzer,
        "matched": record.matched,
        "root_cause_code": record.root_cause_code,
        "confidence": record.confidence,
        "summary": record.summary,
        "evidence_ids": json.loads(record.evidence_ids_json),
        "suggested_checks": json.loads(record.suggested_checks_json),
        "facts": json.loads(record.facts_json),
        "created_at": record.created_at,
    }


def replace_analysis_results(
    incident_id: str,
    results: list[AnalyzerResult],
) -> list[dict[str, Any]]:
    session_factory = get_session_factory()
    with session_factory() as session:
        session.execute(
            delete(AnalysisResultRecord).where(
                AnalysisResultRecord.incident_id == incident_id
            )
        )
        for result in results:
            session.add(
                AnalysisResultRecord(
                    result_id=result.result_id,
                    incident_id=result.incident_id,
                    analyzer=result.analyzer,
                    matched=result.matched,
                    root_cause_code=result.root_cause_code,
                    confidence=result.confidence,
                    summary=result.summary,
                    evidence_ids_json=json.dumps(result.evidence_ids),
                    suggested_checks_json=json.dumps(
                        result.suggested_checks,
                        ensure_ascii=False,
                    ),
                    facts_json=json.dumps(
                        result.facts,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    created_at=result.created_at,
                )
            )
        session.commit()
    return list_analysis_results(incident_id)


def list_analysis_results(
    incident_id: str,
) -> list[dict[str, Any]]:
    session_factory = get_session_factory()
    with session_factory() as session:
        records = session.scalars(
            select(AnalysisResultRecord)
            .where(AnalysisResultRecord.incident_id == incident_id)
            .order_by(
                AnalysisResultRecord.matched.desc(),
                AnalysisResultRecord.confidence.desc(),
                AnalysisResultRecord.analyzer.asc(),
            )
        ).all()
        return [_as_dict(record) for record in records]
