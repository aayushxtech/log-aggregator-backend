from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
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
    Accepts a list of logs and inserts them all into the database
    """
    db_logs = []

    for log in logs:
        db_log = models.Log(
            level=log.level,
            message=log.message,
            timestamp=log.timestamp,
            service=log.service,
            metadata_=log.metadata_,
        )
        db.add(db_log)
        db_logs.append(db_log)

    db.commit()

    for db_log in db_logs:
        db.refresh(db_log)

    return db_logs
