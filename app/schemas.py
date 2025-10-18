from pydantic import BaseModel
from typing import Optional, Dict, Mapping, List
from datetime import datetime


class AppBase(BaseModel):
    name: str
    description: Optional[str] = None


class AppCreate(AppBase):
    pass


class AppRead(AppBase):
    id: int

    model_config = {"from_attributes": True}


class LogBase(BaseModel):
    level: str
    message: str
    timestamp: Optional[datetime] = None
    metadata_: Optional[Mapping[str, str]] = None
    service: str
    app_id: int
    app: str


class LogCreate(LogBase):
    # timestamp optional: DB can default to now()
    timestamp: Optional[datetime] = None


class LogRead(LogBase):
    id: int

    # allow ORM objects -> pydantic models (Pydantic v2)
    model_config = {"from_attributes": True}


class StatsResponse(BaseModel):
    total_logs: int
    by_level: Optional[Dict[str, int]] = {}
    by_service: Optional[Dict[str, int]] = {}
