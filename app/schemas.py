from pydantic import BaseModel
from typing import Optional, Dict, Mapping
from datetime import datetime


class LogBase(BaseModel):
    level: str
    message: str
    timestamp: datetime
    metadata_: Optional[Dict[str, str]] = None


class LogCreate(LogBase):
    service: str


class LogRead(LogBase):
    id: int
    timestamp: datetime

    class Config:
        orm_mode = True


class StatsResponse(BaseModel):
    total_logs: int
    by_level: Optional[Dict[str, int]] = {}
    by_service: Optional[Dict[str, int]] = {}
