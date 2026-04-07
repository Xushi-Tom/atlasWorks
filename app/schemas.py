"""Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Task schemas
# ---------------------------------------------------------------------------


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=1024)
    data_type: str = Field("GeoTIFF", pattern="^(GeoTIFF|DEM|Other)$")
    task_type: str = Field(
        "process", pattern="^(process|convert|analyze|tile)$"
    )
    input_files: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = Field(None, max_length=1024)
    data_type: str | None = Field(None, pattern="^(GeoTIFF|DEM|Other)$")
    task_type: str | None = Field(
        None, pattern="^(process|convert|analyze|tile)$"
    )
    input_files: list[str] | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    data_type: str
    task_type: str
    input_files: list[str]
    status: str
    progress: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Artifact schemas
# ---------------------------------------------------------------------------


class ArtifactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=1024)
    task_id: int | None = None
    file_path: str = Field(..., min_length=1, max_length=1024)
    file_type: str = Field(
        "GeoTIFF",
        pattern="^(GeoTIFF|DEM|PNG|GeoJSON|Shapefile|CSV|Other)$",
    )
    file_size: int = Field(0, ge=0)
    crs: str | None = None
    bounds: list[float] | None = Field(
        None, description="[minx, miny, maxx, maxy]"
    )
    resolution: float | None = Field(None, gt=0)
    tags: list[str] = Field(default_factory=list)


class ArtifactUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = Field(None, max_length=1024)
    file_type: str | None = Field(
        None,
        pattern="^(GeoTIFF|DEM|PNG|GeoJSON|Shapefile|CSV|Other)$",
    )
    crs: str | None = None
    bounds: list[float] | None = None
    resolution: float | None = Field(None, gt=0)
    tags: list[str] | None = None


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    task_id: int | None
    file_path: str
    file_type: str
    file_size: int
    crs: str | None
    bounds: list[float] | None
    resolution: float | None
    tags: list[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Publication schemas
# ---------------------------------------------------------------------------


class PublicationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=1024)
    artifact_id: int
    publish_type: str = Field(
        "static", pattern="^(tiles|static|wms|api)$"
    )
    endpoint_path: str = Field(..., min_length=1, max_length=512)
    access_level: str = Field("public", pattern="^(public|private)$")


class PublicationUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = Field(None, max_length=1024)
    publish_type: str | None = Field(
        None, pattern="^(tiles|static|wms|api)$"
    )
    endpoint_path: str | None = Field(None, min_length=1, max_length=512)
    access_level: str | None = Field(None, pattern="^(public|private)$")


class PublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    artifact_id: int
    publish_type: str
    endpoint_path: str
    status: str
    access_level: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Summary schema (for dashboard)
# ---------------------------------------------------------------------------


class DashboardStats(BaseModel):
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    failed_tasks: int
    total_artifacts: int
    total_publications: int
    active_publications: int
