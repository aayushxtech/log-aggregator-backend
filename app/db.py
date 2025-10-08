from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

Base = declarative_base()

db = SessionLocal()
