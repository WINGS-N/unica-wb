import json

from .queue import redis_conn

EVENTS_CHANNEL = "un1ca:job_events"


def publish(job) -> None:
    # Anything that moves a job publishes here, so the UI can drop polling and
    # react to the change instead
    if job is None:
        return
    payload = {
        "type": "job",
        "id": str(getattr(job, "id", "") or ""),
        "workspace_id": str(getattr(job, "workspace_id", "") or ""),
        "job_kind": str(getattr(job, "job_kind", "") or "build"),
        "target": str(getattr(job, "target", "") or ""),
        "status": str(getattr(job, "status", "") or ""),
    }
    if not payload["id"]:
        return
    try:
        redis_conn.publish(EVENTS_CHANNEL, json.dumps(payload, ensure_ascii=True))
    except Exception:
        pass
