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
