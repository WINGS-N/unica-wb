import json
from datetime import datetime, timezone

from .queue import redis_conn

PROGRESS_HASH_KEY = "un1ca:firmware_progress"
PROGRESS_CHANNEL = "un1ca:firmware_progress_events"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_map(raw: dict[bytes, bytes]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key_raw, value_raw in raw.items():
        try:
            key = key_raw.decode("utf-8")
            value = json.loads(value_raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(value, dict):
            out[key] = value
    return out


def list_progress() -> dict[str, dict]:
    raw = redis_conn.hgetall(PROGRESS_HASH_KEY)
    return _decode_map(raw)


def set_progress(fw_key: str, payload: dict):
    body = {
        "fw_key": fw_key,
        "updated_at": _now_iso(),
        **payload,
    }
    encoded = json.dumps(body, ensure_ascii=True)
    redis_conn.hset(PROGRESS_HASH_KEY, fw_key, encoded)
    redis_conn.publish(PROGRESS_CHANNEL, encoded)


def remove_progress(fw_key: str):
    redis_conn.hdel(PROGRESS_HASH_KEY, fw_key)
    redis_conn.publish(PROGRESS_CHANNEL, json.dumps({"type": "removed", "fw_key": fw_key}, ensure_ascii=True))


def clear_progress():
    redis_conn.delete(PROGRESS_HASH_KEY)
