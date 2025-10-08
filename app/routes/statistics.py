from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Dict
from sqlalchemy import func

from app import db, models, schemas

router = APIRouter(prefix="/api/v1/stats", tags=["statistics"])


def get_db():
    db_session = db.SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


@router.get("/", response_model=schemas.StatsResponse)
def get_statistics(db: Session = Depends(get_db)):
    """
    Returns aggregated log counts by level and service
    """
    # Count logs by level
    level_counts = dict(
        db.query(models.Log.level, func.count(models.Log.id))
          .group_by(models.Log.level)
          .all()
    )

    # Count logs by service
    service_counts = dict(
        db.query(models.Log.service, func.count(models.Log.id))
          .group_by(models.Log.service)
          .all()
    )

    total_logs = db.query(func.count(models.Log.id)).scalar() or 0

    return {
        "total_logs": int(total_logs),
        "by_level": level_counts,
        "by_service": service_counts
    }
