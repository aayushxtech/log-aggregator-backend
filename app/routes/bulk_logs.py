from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Set
from datetime import datetime

from app import models, schemas, db

router = APIRouter(prefix="/api/v1/bulk_logs", tags=["bulk_logs"])


def get_db():
    db_session = db.SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


@router.post("/", response_model=List[schemas.LogRead])
def create_bulk_logs(logs: List[schemas.LogCreate], db: Session = Depends(get_db)):
    """
    Accepts a list of logs and inserts them all into the database.

    Behavior:
    - Each log must provide either app_id or app (app name).
    - Existing apps are prefetched in a single query.
    - Missing apps (by name) are created in one transactional batch.
    - Logs are inserted in a single transaction for atomicity.
    """
    if not logs:
        return []

    # Collect app_ids referenced and app names referenced
    referenced_app_ids: Set[int] = set()
    referenced_app_names: Set[str] = set()
    for l in logs:
        if l.app_id is not None:
            referenced_app_ids.add(l.app_id)
        if l.app:
            referenced_app_names.add(l.app)

    # Prefetch existing apps by id and name
    existing_apps_by_id: Dict[int, models.App] = {}
    existing_apps_by_name: Dict[str, models.App] = {}

    if referenced_app_ids:
        apps = db.query(models.App).filter(
            models.App.id.in_(list(referenced_app_ids))).all()
        for a in apps:
            existing_apps_by_id[a.id] = a
            existing_apps_by_name[a.name] = a

    if referenced_app_names:
        apps = db.query(models.App).filter(
            models.App.name.in_(list(referenced_app_names))).all()
        for a in apps:
            existing_apps_by_id[a.id] = a
            existing_apps_by_name[a.name] = a

    # Determine missing app names that must be created
    missing_names = referenced_app_names - set(existing_apps_by_name.keys())

    # Create missing apps in bulk
    new_apps = []
    for name in missing_names:
        new_apps.append(models.App(name=name, description=None))
    if new_apps:
        db.add_all(new_apps)
        db.commit()
        # refresh to populate ids
        for a in new_apps:
            db.refresh(a)
            existing_apps_by_id[a.id] = a
            existing_apps_by_name[a.name] = a

    # Validate referenced app_ids exist
    for aid in referenced_app_ids:
        if aid not in existing_apps_by_id:
            raise HTTPException(
                status_code=400, detail=f"App with id {aid} not found")

    # Build Log objects
    db_logs: List[models.Log] = []
    for l in logs:
        # resolve app obj
        app_obj = None
        if l.app_id is not None:
            app_obj = existing_apps_by_id.get(l.app_id)
        elif l.app:
            app_obj = existing_apps_by_name.get(l.app)
        else:
            raise HTTPException(
                status_code=400, detail="Each log must include app_id or app (name)")

        # defensive check (shouldn't happen after validation)
        if not app_obj:
            raise HTTPException(
                status_code=400, detail="Referenced app not found")

        db_log = models.Log(
            level=l.level,
            message=l.message,
            timestamp=l.timestamp,
            service=l.service,
            metadata_=l.metadata_,
            app_id=app_obj.id,
            app=app_obj.name,
        )
        db_logs.append(db_log)

    # Insert all logs in one transaction
    db.add_all(db_logs)
    db.commit()

    # refresh to ensure IDs/timestamps are available
    for entry in db_logs:
        db.refresh(entry)

    return db_logs
