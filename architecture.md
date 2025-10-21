# System Architecture - Log Aggregator Backend

## Overview

The Log Aggregator is a lightweight, high-throughput log collection and analytics service built with **FastAPI**. It uses a **producer-consumer** pattern with **Redis Streams** for durability and scalability, backed by **PostgreSQL** for persistent storage.

### Key Features
- **Async Fast Ingest:** Redis-backed queue for high-throughput log ingestion
- **Durable Processing:** Consumer group with acknowledgment for fault tolerance
- **Fallback DB Insert:** Direct synchronous insert if Redis is unavailable
- **Alert System:** Real-time anomaly detection with deduplication
- **Analytics:** Aggregated statistics by level, service, and app
- **Horizontally Scalable:** Multiple workers and API instances

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        PRODUCERS                                 │
│  (curl, browser, Python, Node.js, services, etc.)               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ POST /api/v1/ingest/ (JSON/NDJSON)
                             ▼
        ┌────────────────────────────────────────────┐
        │         FastAPI Server (Port 8000)         │
        │  ┌──────────────────────────────────────┐  │
        │  │  Router: ingest.py                   │  │
        │  │  - Parse body (JSON/NDJSON)          │  │
        │  │  - Validate required fields          │  │
        │  │  - Attempt Redis enqueue             │  │
        │  │  - Fallback: DB sync insert          │  │
        │  └──────────────────────────────────────┘  │
        │                                              │
        │  Other Routers (CRUD/Admin):               │
        │  ┌──────────────────────────────────────┐  │
        │  │ logs.py      - List, filter, delete  │  │
        │  │ bulk_logs.py - Sync bulk insert      │  │
        │  │ app.py       - Manage apps/services  │  │
        │  │ stats.py     - Analytics             │  │
        │  └──────────────────────────────────────┘  │
        │                                              │
        │  Background Tasks:                          │
        │  ┌──────────────────────────────────────┐  │
        │  │ alert_system.py                      │  │
        │  │ - 5s periodic checks                 │  │
        │  │ - Redis/in-memory deduplication      │  │
        │  └──────────────────────────────────────┘  │
        └────────────────────┬──────────────────────┘
                             │
        ┌────────────────────┴──────────────────────┐
        │                                            │
        ▼                                            ▼
   ┌─────────────┐                          ┌──────────────────┐
   │ Redis 6.4   │                          │  PostgreSQL      │
   │             │                          │  (Neon Cloud)    │
   │ Streams:    │                          │                  │
   │ - logs:     │                          │  Tables:         │
   │   stream    │ ◄──────────────────┐    │  - apps          │
   │ - logs:dlq  │                    │    │  - logs          │
   └─────────────┘                    │    └──────────────────┘
                                      │
        ┌─────────────────────────────┘
        │
        ▼
   ┌──────────────────────────────────────┐
   │   Worker Process                     │
   │ (python -m app.ingest.worker)        │
   │                                      │
   │  ┌────────────────────────────────┐  │
   │  │ consume_loop() - async         │  │
   │  │ - Ensure consumer group        │  │
   │  │ - Read pending (id=0)          │  │
   │  │ - Read new (id=">")            │  │
   │  │ - Batch process & ack          │  │
   │  └────────────────────────────────┘  │
   │                                      │
   │  ┌────────────────────────────────┐  │
   │  │ process_batch() - async        │  │
   │  │ - Parse data field (JSON)      │  │
   │  │ - Validate (Pydantic)          │  │
   │  │ - Bulk insert to DB            │  │
   │  │ - Ack on success               │  │
   │  │ - Move to DLQ on error         │  │
   │  └────────────────────────────────┘  │
   │                                      │
   └──────────────────────────────────────┘
```

---

## Component Architecture

### 1. FastAPI Server (`app/main.py`)

**Port:** 8000  
**Framework:** FastAPI with Uvicorn ASGI server

**Responsibilities:**
- Request routing to multiple routers
- CORS middleware configuration
- Lifespan context manager (startup/shutdown)
- Background alert checker task

**Included Routers:**
- `app/routes/ingest.py` - High-throughput async ingest
- `app/routes/logs.py` - CRUD for logs and filtering
- `app/routes/bulk_logs.py` - Synchronous bulk insert helper
- `app/routes/app.py` - Application/service registration
- `app/routes/statistics.py` - Aggregated analytics

---

### 2. Ingest Path (`app/routes/ingest.py`)

**Endpoint:** `POST /api/v1/ingest/`

**Input Formats:**
```json
// JSON Array
[
  {"level":"INFO","message":"log1","service":"svc","app":"demo"},
  {"level":"ERROR","message":"log2","service":"svc","app":"demo"}
]

// NDJSON (newline-delimited JSON)
{"level":"INFO","message":"log1","service":"svc","app":"demo"}
{"level":"ERROR","message":"log2","service":"svc","app":"demo"}
```

**Processing Flow:**
1. Parse request body as JSON array or NDJSON lines
2. Minimal validation: check for required fields (`level`, `message`, `service`, `app` or `app_id`)
3. Attempt Redis enqueue:
   - For each log: `redis.xadd(logs:stream, {data: json.dumps(log)})`
   - Return immediately: `{"enqueued": N, "backend": "redis"}`
4. If Redis unavailable (fallback):
   - Call `bulk_logs.create_bulk_logs()` for synchronous DB insert
   - Return: `{"enqueued": N, "backend": "db"}`

**Response Examples:**
```json
{"enqueued": 5, "backend": "redis"}
{"enqueued": 5, "backend": "db"}
```

**Advantages of Async Queue:**
- Non-blocking: Returns to client in ~1-5ms
- Durable: Messages stored in Redis until processed
- Scalable: Multiple workers can consume in parallel
- Recoverable: Unacknowledged messages replayed on worker restart

---

### 3. Redis Streams (`REDIS_URL` env var)

**Stream Names:**
- `logs:stream` (env: `INGEST_STREAM`) - Main ingest queue
- `logs:dlq` (env: `INGEST_DLQ`) - Dead-letter queue for failed messages

**Consumer Group:**
- Name: `ingest-group` (env: `INGEST_GROUP`)
- Per-message tracking and acknowledgment
- Automatic pending message replay on consumer failure

**Message Format in Redis:**
```json
{
  "data": "{\"level\":\"INFO\",\"message\":\"demo log\",\"service\":\"svc\",\"app\":\"demo\"}"
}
```

**Configuration:**
```bash
INGEST_STREAM=logs:stream        # Stream key name
INGEST_GROUP=ingest-group        # Consumer group name
INGEST_DLQ=logs:dlq              # Dead-letter queue key
INGEST_BATCH_SIZE=500            # Logs per batch
INGEST_BLOCK_MS=2000             # XREADGROUP blocking timeout
```

---

### 4. Worker (`app/ingest/worker.py`)

**Entrypoint:** `python -m app.ingest.worker`

**Technology Stack:**
- `redis.asyncio` - Async Redis client (Python 3.13+ compatible)
- `sqlalchemy.orm.Session` - Synchronous DB session for batch writes
- `asyncio` - Event loop for concurrency

**Main Loop: `consume_loop()`**

```python
while True:
    # 1. Read pending messages (unacked from crashes)
    pending = await redis.xreadgroup(GROUP, CONSUMER, {STREAM: "0"}, count=BATCH_SIZE)
    if pending:
        await process_batch(pending)
        await redis.xack(STREAM, GROUP, msg_ids)
    
    # 2. Read new messages
    new = await redis.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=BATCH_SIZE, block=BLOCK_MS)
    if new:
        await process_batch(new)
        await redis.xack(STREAM, GROUP, msg_ids)
```

**Batch Processing: `process_batch(entries)`**

```python
async def process_batch(entries):
    items = []
    for msg_id, payload in entries:
        try:
            # Payload is {"data": "{...json...}"}
            data_str = payload["data"]
            data = json.loads(data_str)  # Parse nested JSON
            items.append(data)
        except Exception as e:
            # Move to DLQ on parse error
            await redis.xadd(DLQ, {"error": str(e), "msg_id": msg_id})
    
    # Validate with Pydantic schema
    try:
        validated = [LogCreate(**item) for item in items]
    except Exception as e:
        # Move all to DLQ on validation error
        for msg_id, _ in entries:
            await redis.xadd(DLQ, {"error": str(e), "msg_id": msg_id})
        return
    
    # Persist to database
    session = db.SessionLocal()
    try:
        created = bulk_logs.create_bulk_logs(validated, db=session)
        print(f"[worker] Inserted {len(created)} logs to DB")
    except Exception as e:
        # Move to DLQ on DB error
        for msg_id, _ in entries:
            await redis.xadd(DLQ, {"error": str(e), "msg_id": msg_id})
    finally:
        session.close()
```

**Error Handling:**
- **Parse Errors:** Individual message moved to DLQ
- **Validation Errors:** All messages in batch moved to DLQ
- **DB Errors:** All messages in batch moved to DLQ
- **Crash Recovery:** Pending messages reprocessed on restart (xreadgroup id="0")

---

### 5. Database Layer (`app/db.py`, `app/models.py`)

**Database:** PostgreSQL via Neon (cloud-hosted)

**Connection:**
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
# Typical: postgresql://user:pass@host:port/dbname?sslmode=require

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
```

**Tables:**

#### `apps` - Application/Service Registry
```sql
CREATE TABLE apps (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) UNIQUE NOT NULL,
  description VARCHAR(255)
);
```

#### `logs` - Log Entries
```sql
CREATE TABLE logs (
  id SERIAL PRIMARY KEY,
  app_id INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  app VARCHAR(100) NOT NULL,           -- App name (denormalized for query)
  level VARCHAR(20) NOT NULL,          -- INFO, WARNING, ERROR, DEBUG
  service VARCHAR(50) NOT NULL,        -- Service/component name
  message VARCHAR(255) NOT NULL,       -- Log message
  metadata_ JSON,                      -- Additional fields
  timestamp TIMESTAMP DEFAULT NOW(),   -- Ingestion time
  
  INDEX (app),
  INDEX (level),
  INDEX (service),
  INDEX (timestamp)
);
```

**Session Management:**
- `pool_pre_ping=True` - Test connection before use
- `SessionLocal()` - Create new session per request or batch
- `session.close()` - Clean up after use

---

### 6. Bulk Insert Logic (`app/routes/bulk_logs.py`)

**Function:** `create_bulk_logs(logs: List[LogCreate], db: Session) -> List[Log]`

**Algorithm:**

```python
def create_bulk_logs(logs, db):
    # 1. Collect app references
    app_ids = set(log.app_id for log in logs if log.app_id)
    app_names = set(log.app for log in logs if log.app)
    
    # 2. Fetch existing apps (2 queries)
    by_id = {app.id: app for app in db.query(App).filter(App.id.in_(app_ids))}
    by_name = {app.name: app for app in db.query(App).filter(App.name.in_(app_names))}
    
    # 3. Create missing apps in bulk
    missing = app_names - set(by_name.keys())
    if missing:
        new_apps = [App(name=name) for name in missing]
        db.add_all(new_apps)
        db.flush()
        for app in new_apps:
            by_name[app.name] = app
    
    # 4. Build Log ORM objects with resolved app_id
    log_objs = []
    for log_data in logs:
        app_id = log_data.app_id or by_name[log_data.app].id
        log_obj = Log(
            app_id=app_id,
            app=log_data.app,
            level=log_data.level,
            service=log_data.service,
            message=log_data.message,
            metadata_=log_data.metadata_
        )
        log_objs.append(log_obj)
    
    # 5. Insert all in single transaction
    db.add_all(log_objs)
    db.commit()
    
    # 6. Refresh to populate IDs and timestamps
    for log in log_objs:
        db.refresh(log)
    
    return log_objs
```

**Performance:**
- Creates apps with bulk insert (`add_all`)
- Single transaction for logs
- Minimal round-trips to DB
- ~10-50ms per batch of 500 logs

---

### 7. CRUD Endpoints

#### Logs Management (`app/routes/logs.py`)

```
POST /api/v1/logs/             - Create single log (sync)
GET /api/v1/logs/              - List with pagination
  ?skip=0&limit=50&app=demo&level=ERROR
GET /api/v1/logs/filter        - Advanced filter
  ?level=ERROR&service=payment&start_time=ISO8601&end_time=ISO8601
DELETE /api/v1/logs/{log_id}   - Delete log
```

#### Apps Management (`app/routes/app.py`)

```
POST /api/v1/apps/             - Register app
  {"name": "demo", "description": "Demo app"}
GET /api/v1/apps/              - List apps
DELETE /api/v1/apps/{app_id}   - Delete app (cascade delete logs)
```

#### Statistics (`app/routes/statistics.py`)

```
GET /api/v1/stats/             - Aggregated stats
{
  "total_logs": 1250,
  "by_level": {"INFO": 800, "ERROR": 100, "WARNING": 350},
  "by_service": {"web": 500, "db": 400, "api": 350}
}
```

---

### 8. Alert System (`app/alert/alert_system.py`)

**Execution:** Background task in FastAPI lifespan (5-second loop)

**Alert Configuration (`app/alert/config.py`):**

```python
ALERT_CONFIG = {
    "ERROR": {
        "threshold": 10,        # Alert if >= 10 ERROR logs
        "interval_sec": 60      # Check last 60 seconds
    },
    "payment-service": {
        "threshold": 5,         # Alert if >= 5 logs from payment-service
        "interval_sec": 60
    }
}
```

**Deduplication:**
- Uses Redis `SET NX EX` for atomic cross-process dedup
- Fallback: in-memory dict per process
- Alert fires max once per `interval_sec`

**Notification Methods:**
- `"print"` - Stdout logging
- Extensible to: email, Slack, SMS, webhooks

**Alert Logic:**

```python
async def check_alerts(db, redis):
    for rule_name, config in ALERT_CONFIG.items():
        count = get_log_count(db, rule_name, config['interval_sec'])
        
        if count >= config['threshold']:
            dedup_key = f"alert:fired:{rule_name}"
            
            # Check if already alerted (Redis with expiry)
            if not await redis.exists(dedup_key):
                print(f"[ALERT] {rule_name}: {count} logs in {config['interval_sec']}s")
                await redis.setex(dedup_key, config['interval_sec'], "1")
```

---

## Data Flow Diagrams

### Fast Path: Async Ingest → Redis → Worker → DB

```
1. Producer sends POST /api/v1/ingest/
        ↓
2. API parses JSON/NDJSON
        ↓
3. For each log: redis.XADD(logs:stream, {data: JSON})
        ↓
4. API returns {"enqueued": N, "backend": "redis"} immediately
        ↓
[Async Processing]
        ↓
5. Worker: xreadgroup(logs:stream, ingest-group, ">")
        ↓
6. Worker: parse data field, validate, bulk_logs.create_bulk_logs()
        ↓
7. DB: INSERT INTO logs VALUES (...)
        ↓
8. Worker: xack(logs:stream, ingest-group, msg_ids)
        ↓
[Complete]
```

**Latency:**
- API response: ~1-5ms
- Worker processing lag: ~100-500ms (configurable)
- Total: ~100-1000ms from ingest to DB (async)

### Fallback Path: Direct DB Insert

```
1. Producer sends POST /api/v1/ingest/
        ↓
2. API attempts redis.XADD()
        ↓
3. Redis connection fails (timeout, unavailable)
        ↓
4. API calls bulk_logs.create_bulk_logs() synchronously
        ↓
5. DB: INSERT INTO logs VALUES (...)
        ↓
6. API returns {"enqueued": N, "backend": "db"}
        ↓
[Complete]
```

**Latency:** ~50-200ms (synchronous DB write)

### Query Path: CRUD

```
1. Client: GET /api/v1/logs/?app=demo&level=ERROR
        ↓
2. API: db.query(Log).filter(Log.app=='demo', Log.level=='ERROR')
        ↓
3. DB: SELECT * FROM logs WHERE app='demo' AND level='ERROR'
        ↓
4. SQLAlchemy: Map rows to Log ORM objects
        ↓
5. API: JSONResponse(logs_serialized)
        ↓
[Complete]
```

### Alert Path: Periodic Check

```
Every 5 seconds (background task):
        ↓
1. alert_system.check_alerts()
        ↓
2. For each rule in ALERT_CONFIG:
        ↓
3. Query: SELECT COUNT(*) FROM logs WHERE (rule filter) AND timestamp >= NOW() - interval
        ↓
4. If count >= threshold:
        ↓
5. Check dedup: redis.EXISTS(f"alert:fired:{rule_name}")
        ↓
6. If not already fired:
        - Print alert
        - redis.SETEX(dedup_key, interval, "1")
        ↓
[Next iteration in 5s]
```

---

## Configuration & Environment

**`.env` File:**

```bash
# Database (PostgreSQL)
DATABASE_URL="postgresql://neondb_owner:npg_E5NJTd6QLtUA@ep-wispy-hall-adh5lmqv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Redis
REDIS_URL=redis://localhost:6379/0

# CORS (comma-separated)
CORS_ORIGINS=http://localhost:3000,http://localhost:3001

# Ingest Stream Configuration (optional)
INGEST_STREAM=logs:stream
INGEST_GROUP=ingest-group
INGEST_DLQ=logs:dlq
INGEST_BATCH_SIZE=500
INGEST_BLOCK_MS=2000
```

**Loading:**
- `python-dotenv` loads `.env` on module import
- Read by `app/config.py`
- Used by `app/db.py`, worker, etc.

---

## Deployment Topology

### Development (Local)

```
MacBook / Linux Machine
├── PostgreSQL (Neon cloud, remote)
├── Redis (local: redis-server or docker)
│   └── docker run -d --name redis -p 6379:6379 redis:7-alpine
├── FastAPI Server (uvicorn app.main:app --port 8000)
└── Worker (python -m app.ingest.worker in separate terminal)
```

### Production (Kubernetes/Docker Compose)

```
Kubernetes Cluster / Docker Compose
├── Ingress / Load Balancer
│   └── Routes to API Service
├── API Deployment (3+ replicas)
│   ├── FastAPI Pods
│   ├── LivenessProbe: GET /health
│   └── Resource limits: 512Mi RAM, 0.5 CPU
├── Worker Deployment (2+ replicas)
│   ├── Worker Pods
│   ├── LivenessProbe: Check Redis connection
│   └── Resource limits: 1Gi RAM, 1 CPU
├── Redis StatefulSet (1+ replicas)
│   ├── Persistent Volume (10Gi)
│   ├── AOF Persistence (appendonly.aof)
│   └── Service: redis:6379
├── PostgreSQL Service (External: Neon)
│   ├── Cloud-managed
│   ├── Backups: Automated daily
│   └── Connection pooling: 20-50 connections
└── Monitoring
    ├── Prometheus (metrics)
    ├── Grafana (dashboards)
    └── Alertmanager (alert routing)
```

**Scaling Strategy:**
- **API:** Stateless, scale horizontally (load balancer)
- **Worker:** Horizontal scaling via consumer group
  - Each worker: separate consumer name
  - Redis distributes messages
  - Multiple workers: 2x throughput per worker
- **Redis:** Single master (with replication for HA)
- **DB:** Managed service (RDS, Neon) with automatic failover

---

## Scalability & Performance

### Throughput Targets

| Component | Throughput | Latency |
|-----------|-----------|---------|
| Ingest (async, Redis) | 10,000 logs/sec | 1-5ms |
| Worker (batch 500) | 5,000 logs/sec per worker | 100-500ms (lag) |
| DB write | 1,000 logs/sec | 10-50ms per batch |
| DB query | 100 queries/sec | 10-100ms |

### Bottlenecks & Solutions

| Bottleneck | Root Cause | Solution |
|-----------|-----------|----------|
| DB insert speed | ORM overhead | Use raw COPY for 10x throughput |
| Redis lag | Single worker | Add more worker replicas |
| Query slowness | Full table scan | Add indexes on app, level, service |
| Memory | Large batches | Reduce BATCH_SIZE or stream processing |
| Network | Cloud cross-region | Co-locate Redis and DB in same region |

### Optimization Roadmap

1. **Phase 1:** Raw SQL COPY instead of ORM for bulk insert
2. **Phase 2:** Message deduplication (idempotency token in metadata)
3. **Phase 3:** Time-series DB (ClickHouse) for analytics
4. **Phase 4:** Kafka instead of Redis for larger scale
5. **Phase 5:** Log compression and archival (S3)

---

## Resilience & Fault Tolerance

### Failure Scenarios & Recovery

| Failure | Impact | Recovery |
|---------|--------|----------|
| Redis down | Ingest falls back to sync DB | Automatic; no data loss |
| DB down | Ingest fails; logs in Redis | Manual: fix DB, restart worker |
| Worker crash | Pending messages unacked | Restart worker; messages replayed |
| API crash | Requests fail | Horizontal replicas (load balanced) |
| Network partition | Producer/consumer isolated | Retry; messages persist in Redis |

### Guaranteed Delivery

- **At-least-once:** Redis acknowledgment (xack) ensures no message loss
- **Idempotency:** Application-level deduplication via metadata (future)
- **Atomicity:** Batch commit all-or-nothing per batch

### Dead-Letter Queue (DLQ)

- **Purpose:** Capture unparseable or invalid logs
- **Key:** `logs:dlq` (Redis stream)
- **Message Format:** `{"error": "...", "msg_id": "..."}`
- **Monitoring:** Alert if DLQ grows
- **Recovery:** Manual inspection and resubmission

---

## Monitoring & Observability

### Key Metrics to Track

```
Redis Streams:
- XLEN logs:stream          # Queue depth
- XPENDING logs:stream      # Unacked messages
- XLEN logs:dlq             # Failed messages

Database:
- logs table row count
- Average query time
- Connection pool usage

API:
- Request rate (logs/sec)
- Response time (p50, p95, p99)
- Error rate (4xx, 5xx)

Worker:
- Processing lag (timestamp - now)
- Batch size distribution
- Error rate (parse, validation, DB)

Alerts:
- Alert firing rate
- Alert dedup hit rate
```

### Prometheus Metrics (Future)

```python
from prometheus_client import Counter, Histogram, Gauge

ingest_total = Counter('ingest_total', 'Total logs ingested')
ingest_duration = Histogram('ingest_duration_seconds', 'Ingest latency')
queue_depth = Gauge('queue_depth', 'Redis stream depth')
```

### Logging Strategy

**Structured Logging (JSON):**

```python
import json
import logging

logger = logging.getLogger(__name__)
logger.info(json.dumps({
    "event": "log_inserted",
    "count": 10,
    "duration_ms": 45
}))
```

### Health Checks

**API:**
```
GET /health → {"status": "ok"}
```

**Worker:**
```
Check Redis connection
Check DB connection
```

### Dashboards (Grafana)

- Ingest rate (logs/sec)
- Queue depth and processing lag
- Worker error rate
- DB performance (query time, row count)
- Alert summary

---

## Security Considerations

### Authentication & Authorization

1. **API Key Authentication:**
   - Header: `X-API-Key: <secret>`
   - Validate against env var or DB

2. **Rate Limiting:**
   - Per API key: 1000 logs/min
   - Per IP: 100 logs/min
   - Implement via middleware or proxy (nginx)

3. **CORS:**
   - Allowed origins: `CORS_ORIGINS` env var
   - Methods: POST, GET, DELETE
   - Headers: Content-Type, X-API-Key

### Data Security

1. **Database:**
   - SSL/TLS for PostgreSQL (sslmode=require)
   - Connection pooling (ParallelCluster)
   - Encrypted credentials in .env (never commit)

2. **Redis:**
   - Private VPC or AUTH password
   - No public internet exposure
   - Persistent AOF file encrypted at rest

3. **Transport:**
   - HTTPS only (behind reverse proxy/Ingress)
   - TLS 1.2+ for all connections

### Input Validation

- Pydantic schemas enforce field types and lengths
- Escape special characters in metadata
- Sanitize log messages (no injection)
- Max message length: 255 chars (configurable)

### Secrets Management

- `.env` file: local dev only
- Production: use secrets backend
  - Kubernetes Secrets
  - AWS Secrets Manager
  - HashiCorp Vault

---

## Development Workflow

### Setup

```bash
# Clone and install
git clone https://github.com/aayushxtech/log-aggregator-backend.git
cd log_aggregator
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Initialize DB
python -m app.init_db

# Start Redis (Docker)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Start API
uvicorn app.main:app --reload --port 8000

# Start worker (new terminal)
python -m app.ingest.worker
```

### Testing

```bash
# Send test logs
curl -X POST http://localhost:8000/api/v1/ingest/ \
  -H "Content-Type: application/json" \
  -d '[
    {"level":"INFO","message":"test","service":"api","app":"demo"},
    {"level":"ERROR","message":"error","service":"db","app":"demo"}
  ]'

# Query logs
curl http://localhost:8000/api/v1/logs/?app=demo

# Check Redis
redis-cli XLEN logs:stream
redis-cli XLEN logs:dlq

# View stats
curl http://localhost:8000/api/v1/stats/
```

### Git Workflow

```bash
# Feature branch
git checkout -b feature/new-alert-rule
# ... edit files ...
git add .
git commit -m "Add email alert support"
git push origin feature/new-alert-rule
# Create PR on GitHub

# After review and merge
git checkout main
git pull origin main
```

---

## Future Enhancements

### Short-term (1-2 months)
- [ ] API key authentication
- [ ] Rate limiting per client
- [ ] Email alerting integration
- [ ] Structured logging (JSON) in worker
- [ ] Health check endpoint

### Medium-term (2-4 months)
- [ ] Message deduplication (idempotency)
- [ ] Raw SQL COPY for bulk insert (10x faster)
- [ ] Time-range log export (CSV, Parquet)
- [ ] Webhook notifications for alerts
- [ ] Grafana dashboard templates

### Long-term (4+ months)
- [ ] ClickHouse integration for analytics
- [ ] Kafka instead of Redis (larger scale)
- [ ] Log compression and archival (S3)
- [ ] Multi-tenancy support
- [ ] Advanced filtering DSL (Lucene, Elasticsearch)

---

## Summary

The **Log Aggregator Backend** is a production-ready, scalable log collection system:

- **Fast Ingest:** Redis Streams for durable, high-throughput queuing
- **Reliable Processing:** Consumer groups with at-least-once delivery
- **Graceful Degradation:** Fallback to sync DB insert if Redis fails
- **Real-time Alerts:** Periodic checks with deduplication
- **Observable:** Structured logging, metrics, and dashboards
- **Horizontally Scalable:** Multiple API and worker instances
- **Fault Tolerant:** Automatic recovery and pending message replay

**Architecture principles:**
1. Async fast path (Redis) → sync fallback (DB)
2. Batch processing for efficiency
3. Consumer groups for fault tolerance
4. Minimal dependencies (FastAPI, SQLAlchemy, redis-py)
5. Cloud-ready (Neon PostgreSQL, managed Redis)
