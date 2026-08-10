import json
import time
from datetime import UTC, datetime

from .queue import redis_conn

PROGRESS_HASH_KEY = "un1ca:firmware_progress"
PROGRESS_CHANNEL = "un1ca:firmware_progress_events"

# Terminal entries linger just long enough for the UI to show the final state,
# then drop out of the snapshot so a page reload never resurrects a dead bar
TERMINAL_TTL_SEC = 20
TERMINAL_STATES = {"completed", "failed", "canceled"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def progress_key(scope: str, fw_key: str) -> str:
    return f"{scope or 'shared'}:{fw_key}"


def _decode_map(raw: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key_raw, value_raw in raw.items():
        try:
            key = key_raw.decode("utf-8") if isinstance(key_raw, bytes) else str(key_raw)
            value = json.loads(value_raw.decode("utf-8") if isinstance(value_raw, bytes) else str(value_raw))
        except Exception:
            continue
        if isinstance(value, dict):
            out[key] = value
    return out


def list_progress() -> dict[str, dict]:
    try:
        raw = redis_conn.hgetall(PROGRESS_HASH_KEY)
    except Exception:
        return {}
    items = _decode_map(raw)
    now = time.time()
    expired = [k for k, v in items.items() if float(v.get("expires_at") or 0) and float(v["expires_at"]) < now]
    for key in expired:
        items.pop(key, None)
        try:
            redis_conn.hdel(PROGRESS_HASH_KEY, key)
        except Exception:
            pass
    return items


def set_progress(scope: str, fw_key: str, payload: dict):
    key = progress_key(scope, fw_key)
    body = {
        "key": key,
        "scope": scope or "shared",
        "fw_key": fw_key,
        "updated_at": _now_iso(),
        **payload,
    }
    if str(body.get("status") or "") in TERMINAL_STATES:
        body["expires_at"] = time.time() + TERMINAL_TTL_SEC
    encoded = json.dumps(body, ensure_ascii=True)
    try:
        redis_conn.hset(PROGRESS_HASH_KEY, key, encoded)
        redis_conn.publish(PROGRESS_CHANNEL, encoded)
    except Exception:
        pass


def remove_progress(scope: str, fw_key: str):
    key = progress_key(scope, fw_key)
    try:
        redis_conn.hdel(PROGRESS_HASH_KEY, key)
        redis_conn.publish(PROGRESS_CHANNEL, json.dumps({"type": "removed", "key": key}, ensure_ascii=True))
    except Exception:
        pass


def clear_progress():
    try:
        redis_conn.delete(PROGRESS_HASH_KEY)
    except Exception:
        pass
