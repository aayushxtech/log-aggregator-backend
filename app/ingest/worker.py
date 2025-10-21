import asyncio
import json
import os
import uuid
import redis.asyncio as aioredis  # type: ignore
from typing import List
from sqlalchemy.orm import Session

from app import db, schemas
from app.routes import bulk_logs

STREAM = os.getenv("INGEST_STREAM", "logs:stream")
GROUP = os.getenv("INGEST_GROUP", "ingest-group")
CONSUMER = os.getenv("INGEST_CONSUMER", f"consumer-{uuid.uuid4().hex[:8]}")
BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "500"))
BLOCK_MS = int(os.getenv("INGEST_BLOCK_MS", "2000"))
DLQ = os.getenv("INGEST_DLQ", "logs:dlq")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def ensure_group(r: aioredis.Redis):
    """Ensure consumer group exists."""
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        print(f"[worker] Created consumer group '{GROUP}'")
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            print(f"[worker] Error creating group: {e}")


async def process_batch(entries: List[tuple], r: aioredis.Redis):
    """
    Process and persist logs to DB.
    entries: list of tuples (msg_id, payload_dict)
    """
    if not entries:
        return

    # Extract and parse the 'data' field from each entry
    items = []
    for _id, payload in entries:
        try:
            # payload is like {"data": "{\"level\": \"INFO\", ...}"}
            data_str = payload.get("data")
            if isinstance(data_str, str):
                data = json.loads(data_str)  # Parse the JSON string
            else:
                data = data_str
            items.append(data)
        except Exception as e:
            print(f"[worker] Error parsing data field: {e}")
            # Move to DLQ
            await r.xadd(DLQ, {"error": f"Failed to parse data: {e}", "msg_id": _id})
            continue

    if not items:
        return

    # Validate
    try:
        validated = [schemas.LogCreate(**item) for item in items]
    except Exception as e:
        print(f"[worker] Validation error: {e}")
        # Move to DLQ
        for msg_id, _ in entries:
            await r.xadd(DLQ, {"error": str(e), "msg_id": msg_id})
        return

    # Persist to DB
    session: Session = db.SessionLocal()
    try:
        created = bulk_logs.create_bulk_logs(validated, db=session)
        print(f"[worker] Successfully inserted {len(created)} logs to DB")
    except Exception as e:
        print(f"[worker] DB error: {e}")
        # Move to DLQ
        for msg_id, _ in entries:
            await r.xadd(DLQ, {"error": str(e), "msg_id": msg_id})
    finally:
        session.close()


async def consume_loop():
    """Main consumer loop."""
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await ensure_group(r)

    print(
        f"[worker] Starting consumption from stream '{STREAM}' in group '{GROUP}'")

    while True:
        try:
            # Read pending messages first
            pending = await r.xreadgroup(GROUP, CONSUMER, {STREAM: "0"}, count=BATCH_SIZE)
            if pending:
                stream_key, messages = pending[0]
                entries = [(msg_id, msg_data) for msg_id, msg_data in messages]
                await process_batch(entries, r)
                # Acknowledge messages
                for msg_id, _ in entries:
                    await r.xack(STREAM, GROUP, msg_id)

            # Read new messages
            new = await r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=BATCH_SIZE, block=BLOCK_MS)
            if new:
                stream_key, messages = new[0]
                entries = [(msg_id, msg_data) for msg_id, msg_data in messages]
                await process_batch(entries, r)
                # Acknowledge messages
                for msg_id, _ in entries:
                    await r.xack(STREAM, GROUP, msg_id)

        except Exception as e:
            print(f"[worker] Error in consume loop: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(consume_loop())
