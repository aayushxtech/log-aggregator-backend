# Log Aggregator & Analytics API

A lightweight FastAPI service for collecting, storing, and querying application logs with simple analytics.

- Project location: /home/aayushxtech/Project/aoop-project/log_aggregator
- Python: tested with Python 3.13
- Frameworks / major deps: FastAPI, SQLAlchemy, Pydantic, Uvicorn, python-dotenv  
  See: `requirements.txt`

Contents

- app/main.py — application bootstrap and router registration ([app/main.py](app/main.py))
- app/routes/logs.py — CRUD and filter endpoints for logs ([app/routes/logs.py](app/routes/logs.py))
- app/routes/bulk_logs.py — bulk insert endpoint ([app/routes/bulk_logs.py](app/routes/bulk_logs.py))
- app/routes/statistics.py — aggregated statistics endpoint ([app/routes/statistics.py](app/routes/statistics.py))
- app/models.py — SQLAlchemy ORM model `Log` ([app/models.py](app/models.py))
- app/schemas.py — Pydantic request/response schemas ([app/schemas.py](app/schemas.py))
- app/db.py — DB engine, SessionLocal and Base ([app/db.py](app/db.py))
- app/init_db.py — helper to create tables ([app/init_db.py](app/init_db.py))
- app/config.py — loads environment variables (DATABASE_URL) ([app/config.py](app/config.py))
- .env — DB connection (not tracked) (.env)
- .gitignore — recommended ignores (.gitignore)

Quick setup

1. Create and activate a virtual environment (Linux):

   ```zsh
   python3.13 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure the database connection in `.env` at project root. Use a clean key/value format (no surrounding quotes, no spaces):

   ```.env
   DATABASE_URL=postgresql://user:pass@host:port/dbname?sslmode=require
   ```

   See [app/config.py](app/config.py) for how the value is loaded.

3. Initialize database tables:
   - From project root:

     ```zsh
     cd /home/aayushxtech/Project/aoop-project/log_aggregator
     python3.13 -m app.init_db
     ```

   This calls [`app/init_db.py`](app/init_db.py) which runs `Base.metadata.create_all(bind=engine)` where `Base` and `engine` come from [`app/db.py`](app/db.py).

Run the app (development)

- From project root:

  ```zsh
  uvicorn app.main:app --reload --port 8000
  ```

- Open interactive docs: http://127.0.0.1:8000/docs

Primary endpoints

- Create log: POST /api/v1/logs/ ([app/routes/logs.py](app/routes/logs.py))  
- Read logs / filter: GET /api/v1/logs/ and /api/v1/logs/filter
- Read single log: GET /api/v1/logs/{log_id}
- Delete log: DELETE /api/v1/logs/{log_id} — note: current implementation returns a message string but the route is declared with response_model=LogRead; see "Known issues".
- Bulk insert: POST /api/v1/bulk_logs/ ([app/routes/bulk_logs.py](app/routes/bulk_logs.py))
- Stats: GET /api/v1/stats/ ([app/routes/statistics.py](app/routes/statistics.py))

Schemas and model notes

- Pydantic schemas: [`app/schemas.py`](app/schemas.py)
  - LogCreate — input for create
  - LogRead — output (orm_mode enabled)
  - StatsResponse — aggregates (total_logs, by_level, by_service)
- ORM model: [`app/models.py`](app/models.py)
  - Field `metadata_` maps to a JSON column; intentionally named `metadata_` to avoid colliding with SQLAlchemy Declarative's reserved attribute `metadata`.

Known issues

- .env formatting: do not include surrounding quotes or spaces around `DATABASE_URL` — use `KEY=VALUE`.
- Reserved attribute collision: do not name model attributes `metadata` (SQLAlchemy reserves it). The repo uses `metadata_` to avoid the conflict. See [`app/models.py`](app/models.py) and [`app/schemas.py`](app/schemas.py).
- Delete endpoint mismatch: [`app/routes/logs.py`](app/routes/logs.py) declares `response_model=LogRead` but returns a message dict. Either change response_model or return the deleted object.
- DB engine: [`app/db.py`](app/db.py) uses `declarative_base()` from `sqlalchemy.ext.declarative` — consider switching to `from sqlalchemy.orm import declarative_base` for SQLAlchemy 2.x compatibility.

## API Reference

Base URL (development)
- http://127.0.0.1:8000

Interactive docs
- Swagger UI: GET /docs
- OpenAPI JSON: GET /openapi.json

All routes are prefixed where indicated. Request/response examples assume JSON and ISO8601 timestamps with timezone (e.g. 2025-10-09T12:34:56+00:00).

---

### Root
- GET /
  - Purpose: health / welcome
  - Response 200:
    ```json
    { "message": "Log Aggregation Service is up and running" }
    ```

### Logs (prefix: /api/v1/logs)

- POST /api/v1/logs/
  - Purpose: create a single log
  - Request body (LogCreate):
    ```json
    {
      "level": "ERROR",
      "message": "Something went wrong",
      "timestamp": "2025-10-09T12:34:56+00:00",
      "metadata_": {"request_id": "abc"},
      "service": "payment-service"
    }
    ```
  - Response 200 (LogRead):
    ```json
    {
      "id": 1,
      "level": "ERROR",
      "message": "Something went wrong",
      "timestamp": "2025-10-09T12:34:56+00:00",
      "metadata_": {"request_id": "abc"}
    }
    ```
  - Notes: `LogRead` currently omits `service` from its declared fields; include `service` in responses by adding it to `LogRead` if required.

- GET /api/v1/logs/
  - Purpose: list logs with pagination
  - Query params:
    - skip: int (default 0)
    - limit: int (default 50)
  - Response 200: List[LogRead]
  - Example:
    ```
    GET /api/v1/logs?skip=0&limit=25
    ```

- GET /api/v1/logs/{log_id}
  - Purpose: fetch a single log by id
  - Path param: log_id (int)
  - Response:
    - 200 LogRead on success
    - 404 if not found

- GET /api/v1/logs/filter
  - Purpose: query logs with filters
  - Query params (all optional):
    - level: string (exact match)
    - service: string (exact match)
    - start_time: datetime (ISO8601)
    - end_time: datetime (ISO8601)
    - skip: int
    - limit: int
  - Response 200: List[LogRead]
  - Example:
    ```
    GET /api/v1/logs/filter?level=ERROR&service=payment-service&start_time=2025-10-09T00:00:00Z&end_time=2025-10-10T00:00:00Z
    ```
  - Common 422 cause: unparseable `start_time`/`end_time` formats — use ISO8601 with timezone.

- DELETE /api/v1/logs/{log_id}
  - Purpose: delete a log and return the deleted record
  - Path param: log_id (int)
  - Response:
    - 200 LogRead (deleted record)
    - 404 if not found

---

### Bulk insert (prefix: /api/v1/bulk_logs)

- POST /api/v1/bulk_logs/
  - Purpose: insert multiple logs in a single request
  - Request body: JSON array of LogCreate objects
  - Response 200: JSON array of LogRead objects (created records)
  - Example:
    ```json
    [
      {
        "level": "INFO",
        "message": "start",
        "timestamp": "2025-10-09T12:00:00+00:00",
        "metadata_": null,
        "service": "payment-service"
      },
      {
        "level": "ERROR",
        "message": "failure",
        "timestamp": "2025-10-09T12:01:00+00:00",
        "metadata_": {"code": "E123"},
        "service": "payment-service"
      }
    ]
    ```

---

### Statistics (prefix: /api/v1/stats)

- GET /api/v1/stats/
  - Purpose: aggregated counts of logs
  - Response model (StatsResponse):
    ```json
    {
      "total_logs": 123,
      "by_level": {"ERROR": 10, "INFO": 100},
      "by_service": {"payment-service": 50, "auth-service": 73}
    }
    ```
  - Notes: counts are computed from stored logs; timestamps are considered in queries used by the alert system.

---

### Alerts (background, not HTTP)
- The alert system runs as a background task (enabled by default, controlled via ENABLE_ALERTS env var).
- Configurable in: app/alert/config.py (ALERT_CONFIG). Example entry:
  ```py
  "ERROR": {"threshold": 10, "interval_sec": 60}
  ```
- Cross-process deduplication requires Redis (set REDIS_URL); otherwise dedupe is per-process.

---

### Useful developer notes
- .env formatting: keys must be KEY=VALUE with no surrounding quotes. Example:
  ```
  DATABASE_URL=postgresql://user:pass@host:port/dbname?sslmode=require
  CORS_ORIGINS=http://localhost:3000,http://your-frontend.example.com
  ENABLE_ALERTS=true
  REDIS_URL=redis://localhost:6379/0
  ```
- Use uvicorn to run:
  ```
  uvicorn app.main:app --reload --port 8000
  ```
  For production use a process manager and enable Redis-based dedupe if running multiple workers.

If you want, I can produce a machine-readable OpenAPI snippet trimmed to only the endpoints you want to show on the dashboard.
