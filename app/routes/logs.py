from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app import models, schemas, db

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


def get_db():
    db_session = db.SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


@router.post("/", response_model=schemas.LogRead)
def create_log(log: schemas.LogCreate, db: Session = Depends(get_db)):
    """
    Create a log associated with an App.
    - If `log.app_id` is provided, it must reference an existing App.
    - Otherwise `log.app` (app name) will be used; the App will be created if it doesn't exist.
    """
    # Resolve or create App
    app_obj = None
    if getattr(log, "app_id", None):
        app_obj = db.query(models.App).filter(
            models.App.id == log.app_id).first()
        if not app_obj:
            raise HTTPException(
                status_code=400, detail="App with given app_id not found")
    else:
        # use provided app name (required if no app_id)
        if not getattr(log, "app", None):
            raise HTTPException(
                status_code=400, detail="Either app_id or app (name) must be provided")
        app_obj = db.query(models.App).filter(
            models.App.name == log.app).first()
        if not app_obj:
            # create app on-the-fly
            app_obj = models.App(name=log.app, description=None)
            db.add(app_obj)
            db.commit()
            db.refresh(app_obj)

    new_log = models.Log(
        level=log.level,
        message=log.message,
        service=log.service,
        timestamp=log.timestamp,
        metadata_=getattr(log, "metadata_", None),
        app_id=app_obj.id,
        app=app_obj.name,
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    return new_log


@router.get("/", response_model=List[schemas.LogRead])
def read_logs(
    skip: int = 0,
    limit: int = 50,
    app_id: Optional[int] = None,
    app: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    List logs. Optional filters: app_id or app (name).
    """
    query = db.query(models.Log)
    if app_id is not None:
        query = query.filter(models.Log.app_id == app_id)
    if app is not None:
        query = query.filter(models.Log.app == app)
    logs = query.offset(skip).limit(limit).all()
    return logs


@router.get("/{log_id}", response_model=schemas.LogRead)
def read_log(log_id: int, db: Session = Depends(get_db)):
    log = db.query(models.Log).filter(models.Log.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    return log


@router.get("/filter", response_model=List[schemas.LogRead])
def filter_logs(
    level: Optional[str] = None,
    service: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    app_id: Optional[int] = None,
    app: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    query = db.query(models.Log)

    if level:
        query = query.filter(models.Log.level == level)
    if service:
        query = query.filter(models.Log.service == service)
    if start_time:
        query = query.filter(models.Log.timestamp >= start_time)
    if end_time:
        query = query.filter(models.Log.timestamp <= end_time)
    if app_id is not None:
        query = query.filter(models.Log.app_id == app_id)
    if app is not None:
        query = query.filter(models.Log.app == app)

    logs = query.offset(skip).limit(limit).all()
    return logs


@router.delete("/{log_id}", response_model=schemas.LogRead)
def delete_log(log_id: int, db: Session = Depends(get_db)):
    log = db.query(models.Log).filter(models.Log.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    # Build return payload before deleting (so response_model matches)
    deleted_payload = {
        "id": log.id,
        "level": log.level,
        "service": log.service,
        "message": log.message,
        "timestamp": log.timestamp,
        "metadata_": log.metadata_,
    }
    db.delete(log)
    db.commit()
    return deleted_payload
