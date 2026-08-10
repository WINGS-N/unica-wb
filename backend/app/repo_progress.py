import json
from datetime import UTC, datetime

from .queue import redis_conn

PROGRESS_HASH_KEY = "un1ca:repo_progress"
PROGRESS_CHANNEL = "un1ca:repo_progress_events"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _decode(raw) -> dict:
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def list_progress() -> dict[str, dict]:
    try:
        raw = redis_conn.hgetall(PROGRESS_HASH_KEY)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for key_raw, value_raw in raw.items():
        key = key_raw.decode("utf-8") if isinstance(key_raw, bytes) else str(key_raw)
        payload = _decode(value_raw)
        if payload:
            out[key] = payload
    return out


def get_progress(workspace_id: str) -> dict:
    if not workspace_id:
        return {}
    try:
        raw = redis_conn.hget(PROGRESS_HASH_KEY, workspace_id)
    except Exception:
        return {}
    if not raw:
        return {}
    return _decode(raw)


def set_progress(workspace_id: str, payload: dict):
    if not workspace_id:
        return
    body = {"workspace_id": workspace_id, "updated_at": _now_iso(), **payload}
    encoded = json.dumps(body, ensure_ascii=True)
    try:
        redis_conn.hset(PROGRESS_HASH_KEY, workspace_id, encoded)
        redis_conn.publish(PROGRESS_CHANNEL, encoded)
    except Exception:
        pass


def clear_progress(workspace_id: str | None = None):
    try:
        if workspace_id:
            redis_conn.hdel(PROGRESS_HASH_KEY, workspace_id)
            redis_conn.publish(
                PROGRESS_CHANNEL,
                json.dumps({"type": "removed", "workspace_id": workspace_id}, ensure_ascii=True),
            )
        else:
            redis_conn.delete(PROGRESS_HASH_KEY)
            redis_conn.publish(PROGRESS_CHANNEL, json.dumps({"type": "reset"}, ensure_ascii=True))
    except Exception:
        pass
