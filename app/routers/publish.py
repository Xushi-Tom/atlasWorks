"""Publishing resources router."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Artifact, Publication
from app.schemas import PublicationCreate, PublicationRead, PublicationUpdate

router = APIRouter(prefix="/api/publish", tags=["publish"])


@router.get("/", response_model=list[PublicationRead])
def list_publications(db: Session = Depends(get_db)):
    """Return all publications ordered by creation date descending."""
    return (
        db.query(Publication)
        .order_by(Publication.created_at.desc())
        .all()
    )


@router.post(
    "/", response_model=PublicationRead, status_code=status.HTTP_201_CREATED
)
def create_publication(
    payload: PublicationCreate, db: Session = Depends(get_db)
):
    """Publish an artifact as an externally accessible resource."""
    if db.get(Artifact, payload.artifact_id) is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    # Ensure the endpoint path is unique among active publications
    existing = (
        db.query(Publication)
        .filter(
            Publication.endpoint_path == payload.endpoint_path,
            Publication.status == "active",
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="An active publication already uses this endpoint path",
        )
    pub = Publication(**payload.model_dump())
    db.add(pub)
    db.commit()
    db.refresh(pub)
    return pub


@router.get("/{pub_id}", response_model=PublicationRead)
def get_publication(pub_id: int, db: Session = Depends(get_db)):
    """Return a single publication by ID."""
    pub = db.get(Publication, pub_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return pub


@router.put("/{pub_id}", response_model=PublicationRead)
def update_publication(
    pub_id: int, payload: PublicationUpdate, db: Session = Depends(get_db)
):
    """Update mutable fields of a publication."""
    pub = db.get(Publication, pub_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    updates = payload.model_dump(exclude_none=True)
    # If endpoint_path changes, check uniqueness
    new_path = updates.get("endpoint_path")
    if new_path and new_path != pub.endpoint_path:
        conflict = (
            db.query(Publication)
            .filter(
                Publication.endpoint_path == new_path,
                Publication.status == "active",
                Publication.id != pub_id,
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=400,
                detail="An active publication already uses this endpoint path",
            )
    for field, value in updates.items():
        setattr(pub, field, value)
    db.commit()
    db.refresh(pub)
    return pub


@router.delete("/{pub_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_publication(pub_id: int, db: Session = Depends(get_db)):
    """Remove a publication."""
    pub = db.get(Publication, pub_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    db.delete(pub)
    db.commit()


@router.post("/{pub_id}/toggle", response_model=PublicationRead)
def toggle_publication(pub_id: int, db: Session = Depends(get_db)):
    """Toggle a publication between active and inactive."""
    pub = db.get(Publication, pub_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    pub.status = "inactive" if pub.status == "active" else "active"
    db.commit()
    db.refresh(pub)
    return pub
