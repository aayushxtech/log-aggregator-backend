from fastapi import FastAPI
from app.routes import logs, statistics, bulk_logs
import asyncio
from contextlib import asynccontextmanager
from app.alert.alert_system import check_alerts


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: spawn background alert checker task
    task = asyncio.create_task(check_alerts())
    try:
        yield
    finally:
        # shutdown: cancel background task and await its cancellation
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            print("Alert checker task cancelled")

app = FastAPI(
    title="Log Aggregation & Analytics API",
    version="1.0.0",
    description="A lightweight FastAPI-based service for collecting, viewing, and managing logs.",
    lifespan=lifespan,
)

# Routers
app.include_router(logs.router)
app.include_router(statistics.router)
app.include_router(bulk_logs.router)


@app.get("/")
def root():
    return {"message": "Log Aggregation Service is up and running"}
