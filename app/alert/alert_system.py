import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict
from app import models, db
from app.alert.config import ALERT_CONFIG, NOTIF_METHODS

# try to import async redis client; if missing, fall back to in-memory debounce
_redis = None
try:
    import os
    import redis.asyncio as aioredis
    _redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        _redis = aioredis.from_url(_redis_url, decode_responses=True)
    except Exception:
        _redis = None
except Exception:
    _redis = None


def send_alert(message: str):
    """
    Sends alert using configured notification methods.
    Extendable to email, Slack, SMS, etc.
    """
    for method in NOTIF_METHODS:
        if method == "print":
            print(f"[ALERT] {message}")
        # elif method == "slack":
        #     send_slack_alert(message)
        # elif method == "email":
        #     send_email_alert(message)


# in-memory fallback debounce state (used only if Redis unavailable)
_last_alert_times: Dict[str, datetime] = {}


async def _can_send_dedup(key: str, interval_sec: int) -> bool:
    """
    Returns True if an alert for `key` can be sent (i.e. not sent within interval_sec).
    Uses Redis SET NX EX for cross-process atomicity when available, otherwise uses in-memory debounce.
    """
    if _redis is not None:
        try:
            redis_key = f"alert:lock:{key}"
            # SET key value EX seconds NX -> returns True if set (no prior key), None/False otherwise
            was_set = await _redis.set(redis_key, "1", ex=interval_sec, nx=True)
            return bool(was_set)
        except Exception:
            # if redis fails, gracefully fall back to in-memory
            pass

    # in-memory fallback (per-process only)
    now = datetime.now(timezone.utc)
    last = _last_alert_times.get(key)
    if last is None:
        _last_alert_times[key] = now
        return True
    if (now - last) >= timedelta(seconds=interval_sec):
        _last_alert_times[key] = now
        return True
    return False


async def check_alerts():
    """
    Background task that periodically checks logs and triggers alerts
    based on configured thresholds. Uses Redis for cross-process debounce if available.
    """
    try:
        while True:
            for key, config in ALERT_CONFIG.items():
                now = datetime.now(timezone.utc)
                since = now - timedelta(seconds=config["interval_sec"])

                # perform DB work in a thread to avoid blocking the event loop
                def _sync_count(level: str | None = None, service: str | None = None, since_local=None):
                    session_local = db.SessionLocal()
                    try:
                        q = session_local.query(models.Log)
                        if level is not None:
                            q = q.filter(models.Log.level == level,
                                         models.Log.timestamp >= since_local)
                        else:
                            q = q.filter(models.Log.service == service,
                                         models.Log.timestamp >= since_local)
                        return q.count()
                    finally:
                        session_local.close()

                try:
                    if key.upper() in ["ERROR", "INFO", "WARN", "DEBUG"]:
                        count = await asyncio.to_thread(_sync_count, key.upper(), None, since)
                    else:
                        count = await asyncio.to_thread(_sync_count, None, key, since)

                    if count >= config["threshold"]:
                        # check cross-process dedupe (Redis) or in-memory fallback
                        can_send = await _can_send_dedup(key, config["interval_sec"])
                        if can_send:
                            alert_msg = (
                                f"ALERT: {count} logs for '{key}' "
                                f"in last {config['interval_sec']}s (Threshold: {config['threshold']})"
                            )
                            send_alert(alert_msg)

                except Exception as e:
                    print(f"[Alert System Error] {e}")

            # Sleep to yield event loop and prevent CPU overuse
            await asyncio.sleep(5)

    except asyncio.CancelledError:
        print("[Alert System] Shutting down gracefully...")
        return
