import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    PROJECT_NAME: str = "Log Aggregator"
    # trim surrounding whitespace/quotes if present in .env
    DATABASE_URL: str = os.getenv('DATABASE_URL')
    if DATABASE_URL:
        DATABASE_URL = DATABASE_URL.strip().strip("'\"")


config = Config()
