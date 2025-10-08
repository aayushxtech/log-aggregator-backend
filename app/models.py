from sqlalchemy import Column, Integer, String, JSON, DateTime, func
from app.db import Base


class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False)
    service = Column(String(50), nullable=False)
    message = Column(String(255), nullable=False)
    metadata_ = Column('metadata_', JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
