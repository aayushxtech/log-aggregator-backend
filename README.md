# Log Aggregator & Analytics API

A lightweight FastAPI service for collecting, storing, and querying application logs with simple analytics and a durable ingest path (Redis Streams + worker).

Python: tested with Python 3.13  
See dependencies in: requirements.txt

Contents (notable files)

- app/main.py — application bootstrap and router registration ([app/main.py](app/main.py))
- app/routes/logs.py — CRUD and filter endpoints for logs ([app/routes/logs.py](app/routes/logs.py))
- app/routes/bulk_logs.py — synchronous bulk insert to DB ([app/routes/bulk_logs.py](app/routes/bulk_logs.py))
- app/routes/ingest.py — fast async ingest endpoint that enqueues to Redis Stream ([app/routes/ingest.py](app/routes/ingest.py))
- app/ingest/worker.py — Redis Stream consumer that batches & persists to DB ([app/ingest/worker.py](app/ingest/worker.py))
- app/routes/statistics.py — aggregated statistics ([app/routes/statistics.py](app/routes/statistics.py))
- app/routes/app.py — register/manage apps ([app/routes/app.py](app/routes/app.py))
- app/models.py — SQLAlchemy models `Log` and `App` ([app/models.py](app/models.py))
- app/schemas.py — Pydantic schemas (LogCreate/LogRead/App* etc) ([app/schemas.py](app/schemas.py))
- app/db.py — DB engine, SessionLocal and Base ([app/db.py](app/db.py))
- app/init_db.py — create DB tables helper ([app/init_db.py](app/init_db.py))
- app/config.py — loads .env variables ([app/config.py](app/config.py))
- .env — local env (not tracked)

Design summary

- Producers call POST /api/v1/ingest/ (fast, async). The ingest endpoint enqueues messages into a Redis Stream (STREAM_NAME) and returns immediately with an ack.
- A separate worker (python -m app.ingest.worker) consumes the Redis Stream in batches, validates messages with Pydantic, resolves/creates apps, and persists logs using the bulk writer. Failed/invalid messages are moved to a DLQ stream.
- If Redis is unavailable the ingest endpoint falls back to synchronous bulk insert to the DB.
- CRUD and query endpoints remain available for admin/low-volume use.

Environment / .env
Create a `.env` in the project root (no surrounding quotes, no spaces):

```zsh
DATABASE_URL=postgresql://user:pass@host:port/dbname?sslmode=require
REDIS_URL=redis://localhost:6379/0
CORS_ORIGINS=http://localhost:3000
```

See [app/config.py](app/config.py) for loading behavior.

Quick setup (dev)

1. Clone and enter project root:
   cd /home/aayushxtech/Project/aoop-project/log_aggregator

2. Create & activate venv:
   python3.13 -m venv .venv
   source .venv/bin/activate

3. Install deps:
   pip install -r requirements.txt

4. Ensure .env is configured (see above).

5. Initialize DB tables:
   python -m app.init_db

Run the app (development)

- Start API:
  uvicorn app.main:app --reload --port 8000
- Interactive docs: http://127.0.0.1:8000/docs

Primary HTTP endpoints

- POST /api/v1/ingest/ — fast enqueue (JSON array or NDJSON) to Redis stream (preferred for producers). See [app/routes/ingest.py](app/routes/ingest.py).
- POST /api/v1/logs/ — create single log (sync, creates App if needed). See [app/routes/logs.py](app/routes/logs.py).
- POST /api/v1/bulk_logs/ — synchronous bulk insert (admin/low-volume). See [app/routes/bulk_logs.py](app/routes/bulk_logs.py).
- GET /api/v1/logs/ and /api/v1/logs/filter — query logs.
- GET /api/v1/stats/ — aggregated counts.

Worker / queue details

- Ingest stream: default `logs:stream` (INGEST_STREAM env var).
- Consumer group: default `ingest-group` (INGEST_GROUP).
- DLQ: default `logs:dlq` for invalid/failed messages.
- Worker entrypoint: python -m app.ingest.worker — it:
  - Creates/ensures consumer group, processes any existing pending messages, then reads new messages (xreadgroup).
  - Validates items with schemas.LogCreate and calls bulk_logs.create_bulk_logs to persist.
  - Acks messages only after successful processing; failed messages are moved to DLQ.

Known caveats / recommendations (MVP vs production)

- Redis persistence: enable AOF and mount a volume for Redis in production (docker-compose example below uses appendonly).
- Idempotency: producers should include an idempotency or trace id in metadata_ if dedupe is required; worker does not currently dedupe.
- Bulk persistence performance: current implementation uses SQLAlchemy ORM add_all; for very-high-throughput switch to COPY or bulk_insert_mappings.
- Consumer-group startup: worker handles pending messages on startup; if you recreate the group manually you may need id=0 to pick up pre-existing messages.
- Security: add API keys / rate-limiting if exposing ingest endpoint publicly.

Docker-compose (example)
Place a docker-compose.yml at project root to run Redis + api + worker (sample):

```yaml
version: "3.8"
services:
  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: ["redis-server", "--appendonly", "yes"]

  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=${DATABASE_URL}
    ports:
      - "8000:8000"
    depends_on:
      - redis

  worker:
    build: .
    command: python -m app.ingest.worker
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      - redis
      - api

volumes:
  redis-data:
```

Demo — end-to-end (quick steps)

1. Start Redis (Docker):
   docker run -d --name redis -p 6379:6379 -v redis-data:/data redis:7-alpine redis-server --appendonly yes

2. Ensure .env is set and install deps (see Quick setup).

3. Initialize DB tables:
   python -m app.init_db

4. Start API server (terminal A):
   uvicorn app.main:app --reload --port 8000

5. Start worker (terminal B):
   python -m app.ingest.worker

6. Enqueue test logs (producer):
   - JSON array:
     curl -i -X POST "http://127.0.0.1:8000/api/v1/ingest/" \
       -H "Content-Type: application/json" \
       -d '[{"level":"INFO","message":"demo log","service":"svc","app":"demo"}]'

   - NDJSON:
     printf '{"level":"INFO","message":"a","service":"s","app":"demo"}\n{"level":"ERROR","message":"b","service":"s","app":"demo"}\n' \
       | curl -i -X POST "http://127.0.0.1:8000/api/v1/ingest/" -H "Content-Type: application/x-ndjson" --data-binary @-

   Expected response: {"enqueued": N, "backend": "redis"} (or backend:"db" if Redis unavailable)

7. Verify Redis stream (optional):
   docker exec -it redis redis-cli XLEN logs:stream
   docker exec -it redis redis-cli XRANGE logs:stream - +
   docker exec -it redis redis-cli XLEN logs:dlq

8. After worker processes messages, verify persisted logs:
   curl -sL "http://127.0.0.1:8000/api/v1/logs/?app=demo" | jq .

9. If stream messages remain after starting the worker:
   # recreate group to read from start and restart worker
   docker exec -it redis redis-cli XGROUP DESTROY logs:stream ingest-group || true
   docker exec -it redis redis-cli XGROUP CREATE logs:stream ingest-group 0 MKSTREAM
   python -m app.ingest.worker

Developer notes & tests

- Unit test example for bulk ingestion added under tests/test_bulk_logs.py (use sqlite in-memory for CI).
- Monitor Redis: XLEN logs:stream, XPENDING logs:stream ingest-group, XLEN logs:dlq.
- To run tests:
  pip install pytest
  python -m pytest -q

Contact / next improvements

- Add API key auth and rate-limiting.
- Replace ORM bulk insert with COPY for higher throughput.
- Add Prometheus metrics for stream lag and worker latencies.
- Containerize worker and run under orchestration (Kubernetes / systemd) for reliability.
