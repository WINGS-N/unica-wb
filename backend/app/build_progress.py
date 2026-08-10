import json
import time

from .queue import redis_conn

PROGRESS_HASH_KEY = "un1ca:build_progress"
PROGRESS_CHANNEL = "un1ca:build_progress_events"

TERMINAL_TTL_SEC = 20
TERMINAL_STATES = {"completed", "failed", "canceled"}


def list_progress() -> dict[str, dict]:
    try:
        raw = redis_conn.hgetall(PROGRESS_HASH_KEY)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for key, value in raw.items():
        k = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        try:
            payload = json.loads(value.decode("utf-8") if isinstance(value, bytes) else str(value))
        except Exception:
            continue
        if isinstance(payload, dict):
            out[k] = payload
    now = time.time()
    expired = [k for k, v in out.items() if float(v.get("expires_at") or 0) and float(v["expires_at"]) < now]
    for k in expired:
        out.pop(k, None)
        try:
            redis_conn.hdel(PROGRESS_HASH_KEY, k)
        except Exception:
            pass
    return out


def set_progress(job_id: str, payload: dict):
    data = dict(payload)
    data["job_id"] = job_id
    data.setdefault("ts", int(time.time()))
    if str(data.get("status") or "") in TERMINAL_STATES:
        data["expires_at"] = time.time() + TERMINAL_TTL_SEC
    try:
        redis_conn.hset(PROGRESS_HASH_KEY, job_id, json.dumps(data, ensure_ascii=True))
        redis_conn.publish(PROGRESS_CHANNEL, json.dumps(data, ensure_ascii=True))
    except Exception:
        pass


def remove_progress(job_id: str):
    try:
        redis_conn.hdel(PROGRESS_HASH_KEY, job_id)
        redis_conn.publish(PROGRESS_CHANNEL, json.dumps({"type": "removed", "job_id": job_id}, ensure_ascii=True))
    except Exception:
        pass


def clear_progress():
    try:
        redis_conn.delete(PROGRESS_HASH_KEY)
    except Exception:
        pass
