"""Artifact catalog router."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Artifact, Task
from app.schemas import ArtifactCreate, ArtifactRead, ArtifactUpdate

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/", response_model=list[ArtifactRead])
def list_artifacts(db: Session = Depends(get_db)):
    """Return all artifacts ordered by creation date descending."""
    return db.query(Artifact).order_by(Artifact.created_at.desc()).all()


@router.post("/", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED)
def create_artifact(payload: ArtifactCreate, db: Session = Depends(get_db)):
    """Register a new artifact."""
    if payload.task_id is not None:
        if db.get(Task, payload.task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found")
    artifact = Artifact(**payload.model_dump())
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


@router.get("/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: int, db: Session = Depends(get_db)):
    """Return a single artifact by ID."""
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.put("/{artifact_id}", response_model=ArtifactRead)
def update_artifact(
    artifact_id: int, payload: ArtifactUpdate, db: Session = Depends(get_db)
):
    """Update mutable metadata of an artifact."""
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(artifact, field, value)
    db.commit()
    db.refresh(artifact)
    return artifact


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artifact(artifact_id: int, db: Session = Depends(get_db)):
    """Delete an artifact and its publications."""
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    db.delete(artifact)
    db.commit()


@router.get("/task/{task_id}", response_model=list[ArtifactRead])
def list_artifacts_by_task(task_id: int, db: Session = Depends(get_db)):
    """Return all artifacts belonging to a specific task."""
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return (
        db.query(Artifact)
        .filter(Artifact.task_id == task_id)
        .order_by(Artifact.created_at.desc())
        .all()
    )
