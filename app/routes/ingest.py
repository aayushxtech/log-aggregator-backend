from fastapi import APIRouter, Request, HTTPException
import os
import json
from typing import List, Any

from app import db
from app import schemas
# reuse bulk insert logic as fallback
from app.routes import bulk_logs

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

# try async redis client; if unavailable fallback to None
_redis = None
try:
    import redis.asyncio as aioredis  # type: ignore
    _redis = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
except Exception:
    _redis = None

STREAM_NAME = os.getenv("INGEST_STREAM", "logs:stream")


async def _parse_body(body_bytes: bytes) -> List[Any]:
    if not body_bytes:
        return []
    try:
        payload = json.loads(body_bytes)
        if isinstance(payload, list):
            return payload
        return [payload]
    except Exception:
        # try NDJSON
        try:
            text = body_bytes.decode()
            lines = [line.strip()
                     for line in text.splitlines() if line.strip()]
            return [json.loads(l) for l in lines]
        except Exception:
            raise HTTPException(
                status_code=400, detail="invalid json or ndjson payload")


@router.post("/")
async def ingest(request: Request):
    """
    Lightweight ingest endpoint:
    - Accepts JSON array or NDJSON lines of log objects (shape like LogCreate).
    - Enqueues to Redis Stream (fast) if REDIS_URL set and reachable.
    - If Redis unavailable, falls back to synchronous bulk insert using existing logic.
    """
    body = await request.body()
    items = await _parse_body(body)
    if not items:
        raise HTTPException(status_code=400, detail="empty payload")

    # Quick minimal validation (optional)
    # ensure basic required fields are present in each item (level/message/service)
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise HTTPException(
                status_code=400, detail=f"item {i} is not an object")
        if "level" not in it or "message" not in it or "service" not in it:
            raise HTTPException(
                status_code=400, detail=f"item {i} missing required fields: level/message/service")

    # use a local alias so we don't shadow the module-level _redis
    redis_client = _redis

    if redis_client is not None:
        # enqueue each item (non-blocking)
        enqueued = 0
        for it in items:
            try:
                await redis_client.xadd(STREAM_NAME, {"data": json.dumps(it)})
                enqueued += 1
            except Exception:
                # on Redis write failure, stop using redis for this request and fall back to DB path
                redis_client = None
                break
        if redis_client is not None:
            return {"enqueued": enqueued, "backend": "redis"}
        # else fall through to DB fallback

    # Fallback: use existing bulk insert logic (synchronous) to persist immediately
    session = db.SessionLocal()
    try:
        # validate via Pydantic schema to reuse existing logic safely
        validated = [schemas.LogCreate(**it) for it in items]
        created = bulk_logs.create_bulk_logs(validated, db=session)
        return {"enqueued": len(created), "backend": "db", "created": len(created)}
    finally:
        session.close()
