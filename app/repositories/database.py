import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DEFAULT_DATABASE_PATH = "/root/projects/kubemedic/data/kubemedic.db"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class IncidentRecord(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    alert_name: Mapped[str] = mapped_column(String(200))
    namespace: Mapped[str] = mapped_column(String(253))
    workload: Mapped[str] = mapped_column(String(253), default="unknown")
    pod: Mapped[str] = mapped_column(String(253), default="unknown")
    severity: Mapped[str] = mapped_column(String(40), default="unknown")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[str] = mapped_column(String(40))
    last_seen: Mapped[str] = mapped_column(String(40), index=True)
    resolved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class AlertRecord(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20))
    payload_json: Mapped[str] = mapped_column(Text)
    received_at: Mapped[str] = mapped_column(String(40), index=True)


class IncidentEventRecord(Base):
    __tablename__ = "incident_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
    )
    old_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[str] = mapped_column(String(40), index=True)


def get_database_path() -> Path:
    return Path(os.getenv("KUBEMEDIC_DB_PATH", DEFAULT_DATABASE_PATH))


@lru_cache
def _get_engine(database_path: str) -> Engine:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def get_engine() -> Engine:
    return _get_engine(str(get_database_path()))


def get_session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def init_database() -> None:
    Base.metadata.create_all(get_engine())
