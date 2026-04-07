"""Task management router."""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.models import Artifact, Task
from app.schemas import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TASK_TYPES_OUTPUT: dict[str, str] = {
    "process": "GeoTIFF",
    "convert": "PNG",
    "analyze": "GeoJSON",
    "tile": "Other",
}


def _execute_task(task_id: int, session_factory) -> None:
    """Worker that simulates task execution using the given session factory."""
    db = session_factory()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        task.status = "running"
        task.progress = 50
        task.updated_at = datetime.now(UTC)
        db.commit()

        output_file_type = _TASK_TYPES_OUTPUT.get(task.task_type, "GeoTIFF")
        artifact = Artifact(
            name=f"{task.name} – output",
            description=f"Auto-generated output of task '{task.name}'",
            task_id=task.id,
            file_path=f"outputs/{task.id}/result.{output_file_type.lower()}",
            file_type=output_file_type,
            file_size=0,
        )
        db.add(artifact)

        task.status = "completed"
        task.progress = 100
        task.updated_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        task = db.get(Task, task_id)
        if task:
            task.status = "failed"
            task.error_message = str(exc)
            task.updated_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[TaskRead])
def list_tasks(db: Session = Depends(get_db)):
    """Return all tasks ordered by creation date descending."""
    return db.query(Task).order_by(Task.created_at.desc()).all()


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    """Create a new task."""
    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: Session = Depends(get_db)):
    """Return a single task by ID."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)
):
    """Update mutable fields of a task."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in ("running",):
        raise HTTPException(
            status_code=400, detail="Cannot update a running task"
        )
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(task, field, value)
    task.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """Delete a task and its artifacts."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()


@router.post("/{task_id}/run", response_model=TaskRead)
def run_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger task execution asynchronously."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="Task is already running")
    if task.status == "completed":
        raise HTTPException(
            status_code=400,
            detail="Task already completed; delete and recreate to rerun",
        )
    # Reset any previous failure
    task.status = "pending"
    task.progress = 0
    task.error_message = None
    task.updated_at = datetime.now(UTC)
    db.commit()

    # Pass a session factory bound to the same engine so the background task
    # writes to the same database (critical when using in-memory SQLite in tests).
    SessionFactory = sessionmaker(
        autocommit=False, autoflush=False, bind=db.get_bind()
    )
    background_tasks.add_task(_execute_task, task_id, SessionFactory)

    db.refresh(task)
    return task

