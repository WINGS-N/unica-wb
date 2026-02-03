import json
from datetime import datetime, timezone

from .queue import redis_conn

PROGRESS_KEY = "un1ca:repo_progress"
PROGRESS_CHANNEL = "un1ca:repo_progress_events"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_progress() -> dict:
    raw = redis_conn.get(PROGRESS_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def set_progress(payload: dict):
    body = {"updated_at": _now_iso(), **payload}
    encoded = json.dumps(body, ensure_ascii=True)
    redis_conn.set(PROGRESS_KEY, encoded)
    redis_conn.publish(PROGRESS_CHANNEL, encoded)


def clear_progress():
    redis_conn.delete(PROGRESS_KEY)
    redis_conn.publish(PROGRESS_CHANNEL, json.dumps({"type": "removed"}, ensure_ascii=True))
