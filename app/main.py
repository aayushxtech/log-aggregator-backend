from fastapi import FastAPI
from app.routes import logs, statistics, bulk_logs

app = FastAPI(
    title="Log Aggregation & Analytics API",
    version="1.0.0",
    description="A lightweight FastAPI-based service for collecting, viewing, and managing logs."
)

# Routers
app.include_router(logs.router)
app.include_router(statistics.router)
app.include_router(bulk_logs.router)


@app.get("/")
def root():
    return {"message": "Log Aggregation Service is up and running"}
