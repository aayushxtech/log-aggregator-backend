from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app import models, schemas, db

router = APIRouter(prefix="/api/v1/apps", tags=["apps"])


def get_db():
    db_session = db.SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


@router.post("/", response_model=schemas.AppRead)
def create_app(app_in: schemas.AppCreate, db: Session = Depends(get_db)):
    # prevent duplicate app names
    exists = db.query(models.App).filter(
        models.App.name == app_in.name).first()
    if exists:
        raise HTTPException(
            status_code=400, detail="App with this name already exists")
    db_app = models.App(name=app_in.name, description=app_in.description)
    db.add(db_app)
    db.commit()
    db.refresh(db_app)
    return db_app


@router.get("/", response_model=List[schemas.AppRead])
def list_apps(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    apps = db.query(models.App).offset(skip).limit(limit).all()
    return apps


@router.get("/{app_id}", response_model=schemas.AppRead)
def get_app(app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(models.App).filter(models.App.id == app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="App not found")
    return app_obj


@router.delete("/{app_id}", response_model=schemas.AppRead)
def delete_app(app_id: int, db: Session = Depends(get_db)):
    app_obj = db.query(models.App).filter(models.App.id == app_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="App not found")
    # build return payload before deleting so response_model matches
    deleted_payload = {"id": app_obj.id, "name": app_obj.name,
                       "description": app_obj.description}
    # delete related logs first to avoid FK constraint issues
    db.query(models.Log).filter(models.Log.app_id == app_id).delete()
    db.delete(app_obj)
    db.commit()
    return deleted_payload
