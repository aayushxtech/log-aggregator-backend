import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    PROJECT_NAME: str = "Log Aggregator"
    DATABASE_URL: str = os.getenv('DATABASE_URL')


config = Config()
