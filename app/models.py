"""SQLAlchemy ORM models for AtlasWorks."""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Task(Base):
    """Represents an executable processing task on geospatial data assets."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), default="")
    data_type: Mapped[str] = mapped_column(String(64), default="GeoTIFF")
    task_type: Mapped[str] = mapped_column(String(64), default="process")
    input_files: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", back_populates="task", cascade="all, delete-orphan"
    )


class Artifact(Base):
    """Represents a trackable data product produced by a task."""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), default="")
    task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), default="GeoTIFF")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    crs: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bounds: Mapped[list | None] = mapped_column(JSON, nullable=True)
    resolution: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    task: Mapped["Task | None"] = relationship("Task", back_populates="artifacts")
    publications: Mapped[list["Publication"]] = relationship(
        "Publication", back_populates="artifact", cascade="all, delete-orphan"
    )


class Publication(Base):
    """Represents an externally accessible published resource."""

    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), default="")
    artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    publish_type: Mapped[str] = mapped_column(String(64), default="static")
    endpoint_path: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    access_level: Mapped[str] = mapped_column(String(32), default="public")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    artifact: Mapped["Artifact"] = relationship(
        "Artifact", back_populates="publications"
    )
