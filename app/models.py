from sqlalchemy import Column, Integer, String, JSON, DateTime, func, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False)
    app = Column(String(100), nullable=False, index=True)
    level = Column(String(20), nullable=False)
    service = Column(String(50), nullable=False)
    message = Column(String(255), nullable=False)
    metadata_ = Column('metadata_', JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    app_ = relationship("App", back_populates="logs")


class App(Base):
    __tablename__ = "apps"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    logs = relationship("Log", back_populates="app_")
