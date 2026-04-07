"""AtlasWorks FastAPI application entry point."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Artifact, Publication, Task
from app.routers import artifacts, publish, tasks
from app.schemas import DashboardStats

# Create all database tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AtlasWorks",
    description=(
        "Geospatial data building and publishing service platform. "
        "Organise GeoTIFF / DEM assets into tasks, artifacts and publications."
    ),
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Register API routers
app.include_router(tasks.router)
app.include_router(artifacts.router)
app.include_router(publish.router)


# ---------------------------------------------------------------------------
# Dashboard stats helper
# ---------------------------------------------------------------------------


def _get_stats(db: Session) -> DashboardStats:
    total_tasks = db.query(Task).count()
    return DashboardStats(
        total_tasks=total_tasks,
        pending_tasks=db.query(Task).filter(Task.status == "pending").count(),
        running_tasks=db.query(Task).filter(Task.status == "running").count(),
        completed_tasks=db.query(Task)
        .filter(Task.status == "completed")
        .count(),
        failed_tasks=db.query(Task).filter(Task.status == "failed").count(),
        total_artifacts=db.query(Artifact).count(),
        total_publications=db.query(Publication).count(),
        active_publications=db.query(Publication)
        .filter(Publication.status == "active")
        .count(),
    )


# ---------------------------------------------------------------------------
# Frontend template routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    stats = _get_stats(db)
    recent_tasks = (
        db.query(Task).order_by(Task.created_at.desc()).limit(5).all()
    )
    recent_artifacts = (
        db.query(Artifact).order_by(Artifact.created_at.desc()).limit(5).all()
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "recent_tasks": recent_tasks,
            "recent_artifacts": recent_artifacts,
        },
    )


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db)):
    all_tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    return templates.TemplateResponse(
        "tasks.html", {"request": request, "tasks": all_tasks}
    )


@app.get("/artifacts", response_class=HTMLResponse)
def artifacts_page(request: Request, db: Session = Depends(get_db)):
    all_artifacts = (
        db.query(Artifact).order_by(Artifact.created_at.desc()).all()
    )
    return templates.TemplateResponse(
        "artifacts.html",
        {"request": request, "artifacts": all_artifacts},
    )


@app.get("/publish", response_class=HTMLResponse)
def publish_page(request: Request, db: Session = Depends(get_db)):
    all_pubs = (
        db.query(Publication).order_by(Publication.created_at.desc()).all()
    )
    all_artifacts = (
        db.query(Artifact).order_by(Artifact.name).all()
    )
    return templates.TemplateResponse(
        "publish.html",
        {
            "request": request,
            "publications": all_pubs,
            "artifacts": all_artifacts,
        },
    )


# ---------------------------------------------------------------------------
# Stats API (used by dashboard JS)
# ---------------------------------------------------------------------------


@app.get("/api/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)):
    return _get_stats(db)
