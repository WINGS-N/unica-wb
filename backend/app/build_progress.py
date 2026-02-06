import json
import time

from .queue import redis_conn

PROGRESS_HASH_KEY = "un1ca:build_progress"
PROGRESS_CHANNEL = "un1ca:build_progress_events"


def list_progress() -> dict[str, dict]:
    try:
        raw = redis_conn.hgetall(PROGRESS_HASH_KEY)
    except Exception:
        return {}
    out = {}
    for key, value in raw.items():
        k = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        try:
            payload = json.loads(value.decode("utf-8") if isinstance(value, bytes) else str(value))
        except Exception:
            continue
        if isinstance(payload, dict):
            out[k] = payload
    return out


def set_progress(job_id: str, payload: dict):
    data = dict(payload)
    data["job_id"] = job_id
    data.setdefault("ts", int(time.time()))
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
