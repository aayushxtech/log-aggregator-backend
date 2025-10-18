from fastapi import FastAPI
from app.routes import logs, statistics, bulk_logs, app as apps_router
import asyncio
from contextlib import asynccontextmanager
from app.alert.alert_system import check_alerts
import os
from starlette.middleware.cors import CORSMiddleware

# configure allowed origins via env var (comma-separated) or default to localhost origins
_cors_origins = os.getenv("CORS_ORIGINS")
if _cors_origins:
    origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
else:
    origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
    ]


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

# apply CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Routers
app.include_router(logs.router)
app.include_router(statistics.router)
app.include_router(bulk_logs.router)

# Apps
app.include_router(apps_router.router)


@app.get("/")
def root():
    return {"message": "Log Aggregation Service is up and running"}
