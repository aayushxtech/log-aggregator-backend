import asyncio
import json
import os
import uuid
from typing import List

import redis.asyncio as aioredis
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
    try:
        await r.xgroup_create(STREAM, GROUP, id="$", mkstream=True)
    except Exception:
        # group exists or creation failed — ignore
        pass


async def process_batch(entries: List[tuple]):
    """
    entries: list of tuples (msg_id, payload_dict)
    Uses a DB session and reuses app.routes.bulk_logs.create_bulk_logs logic for persistence.
    """
    if not entries:
        return

    items = [payload for _id, payload in entries]

    # Validate via Pydantic schema to ensure shape & types
    try:
        validated = [schemas.LogCreate(**it) for it in items]
    except Exception as e:
        # move invalid messages to DLQ with reason
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        for msg_id, payload in entries:
            payload_with_err = {
                "payload": json.dumps(payload), "error": str(e)}
            await r.xadd(DLQ, payload_with_err)
        return

    session: Session = db.SessionLocal()
    try:
        # call bulk insert helper (synchronous) passing session
        created = bulk_logs.create_bulk_logs(validated, db=session)
        # created is list of created Log ORM objects
    except Exception as e:
        # On DB failure push entries to DLQ with error
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        for msg_id, payload in entries:
            await r.xadd(DLQ, {"payload": json.dumps(payload), "error": str(e)})
    finally:
        session.close()


async def consume_loop():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    await ensure_group(r)

    # --- process any pending / pre-existing messages first (ID = 0) ---
    try:
        while True:
            resp = await r.xreadgroup(GROUP, CONSUMER, {STREAM: "0"}, count=BATCH_SIZE, block=1000)
            if not resp:
                break
            batch = []
            ids_to_ack = []
            for _stream, messages in resp:
                for msg_id, fields in messages:
                    raw = fields.get("data") or fields.get(b"data")
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        await r.xadd(DLQ, {"payload": raw, "error": "invalid_json"})
                        await r.xack(STREAM, GROUP, msg_id)
                        continue
                    batch.append((msg_id, payload))
                    ids_to_ack.append(msg_id)
            if batch:
                await process_batch(batch)
                if ids_to_ack:
                    await r.xack(STREAM, GROUP, *ids_to_ack)
    except Exception as e:
        print(f"[ingest worker] error processing pending: {e}")

    # --- then process new messages as before (use '>') ---
    while True:
        try:
            resp = await r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=BATCH_SIZE, block=BLOCK_MS)
            if not resp:
                await asyncio.sleep(0.1)
                continue

            # resp is list of (stream, [(id, {field: value}), ...])
            batch = []
            ids_to_ack = []
            for _stream, messages in resp:
                for msg_id, fields in messages:
                    raw = fields.get("data") or fields.get(b"data")
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        # move to DLQ
                        await r.xadd(DLQ, {"payload": raw, "error": "invalid_json"})
                        # still ack the bad message
                        await r.xack(STREAM, GROUP, msg_id)
                        continue
                    batch.append((msg_id, payload))
                    ids_to_ack.append(msg_id)

            if batch:
                # process in background (await so we can ack only when processed)
                await process_batch(batch)
                # ack processed ids
                if ids_to_ack:
                    await r.xack(STREAM, GROUP, *ids_to_ack)

        except Exception as e:
            print(f"[ingest worker] error: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(consume_loop())
    except KeyboardInterrupt:
        print("Consumer stopped")
