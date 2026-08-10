import base64
import json
import logging

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import AppSetting, PushSubscription

logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = "push.vapid_private"
VAPID_PUBLIC_KEY = "push.vapid_public"
VAPID_SUBJECT = "mailto:wings-n@users.noreply.github.com"

# Notification copy lives here rather than in the web app: a push is rendered
# while no page is open, in the language the subscriber picked
MESSAGES = {
    "en": {
        "build_succeeded": ("Build finished", "{target} {version} is ready"),
        "build_failed": ("Build failed", "{target}: {error}"),
        "build_canceled": ("Build canceled", "{target} was stopped"),
        "operation_failed": ("Operation failed", "{name}: {error}"),
        "test": ("UN1CA Builder", "Notifications are on"),
    },
    "ru": {
        "build_succeeded": ("Сборка готова", "{target} {version} собран"),
        "build_failed": ("Сборка упала", "{target}: {error}"),
        "build_canceled": ("Сборка отменена", "{target} остановлен"),
        "operation_failed": ("Операция не удалась", "{name}: {error}"),
        "test": ("UN1CA Builder", "Уведомления включены"),
    },
}


def _get_setting(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value.strip() if row and row.value else ""


def _set_setting(db: Session, key: str, value: str):
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def ensure_vapid_keys(db: Session) -> tuple[str, str]:
    # Generated once and kept in settings, so push works without any manual setup
    private = _get_setting(db, VAPID_PRIVATE_KEY)
    public = _get_setting(db, VAPID_PUBLIC_KEY)
    if private and public:
        return private, public

    vapid = Vapid01()
    vapid.generate_keys()
    private = (
        base64.urlsafe_b64encode(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
        .decode("utf-8")
        .rstrip("=")
    )
    raw_public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    public = base64.urlsafe_b64encode(raw_public).decode("utf-8").rstrip("=")
    _set_setting(db, VAPID_PRIVATE_KEY, private)
    _set_setting(db, VAPID_PUBLIC_KEY, public)
    return private, public


def public_key() -> str:
    db = SessionLocal()
    try:
        _, public = ensure_vapid_keys(db)
        return public
    finally:
        db.close()


def render(kind: str, language: str, **values) -> tuple[str, str]:
    catalog = MESSAGES.get(language if language in MESSAGES else "en", MESSAGES["en"])
    title, body = catalog.get(kind, catalog["test"])
    return title, body.format(**values)


def _send_one(subscription: PushSubscription, payload: dict, private: str) -> bool:
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=private,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=600,
        )
        return True
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", 0)
        # 404 and 410 mean the browser dropped the subscription for good
        if status in (404, 410):
            return False
        logger.warning("push delivery failed: %s", exc)
        return True
    except Exception as exc:
        logger.warning("push delivery error: %s", exc)
        return True


def broadcast(kind: str, url: str = "/jobs", tag: str = "", level: str = "info", **values):
    # Every subscriber gets the message in their own language
    db = SessionLocal()
    try:
        private, _ = ensure_vapid_keys(db)
        subscriptions = db.query(PushSubscription).all()
        if not subscriptions:
            return
        stale = []
        for subscription in subscriptions:
            title, body = render(kind, subscription.language or "en", **values)
            payload = {"title": title, "body": body, "url": url, "tag": tag or kind, "level": level}
            if not _send_one(subscription, payload, private):
                stale.append(subscription)
        for subscription in stale:
            db.delete(subscription)
        if stale:
            db.commit()
    except Exception as exc:
        logger.warning("push broadcast failed: %s", exc)
    finally:
        db.close()


def notify_job(job) -> None:
    # Only outcomes worth interrupting someone for
    status = str(getattr(job, "status", ""))
    kind = str(getattr(job, "job_kind", "build") or "build")
    target = str(getattr(job, "target", "") or "")
    error = str(getattr(job, "error", "") or "").strip().splitlines()[0][:120] if getattr(job, "error", None) else ""

    if kind == "build":
        version = ".".join(
            str(getattr(job, part, "") or "0") for part in ("version_major", "version_minor", "version_patch")
        )
        if status == "succeeded":
            broadcast(
                "build_succeeded", url="/jobs", tag=f"job-{job.id}", level="success", target=target, version=version
            )
        elif status == "failed":
            broadcast(
                "build_failed",
                url="/logs",
                tag=f"job-{job.id}",
                level="error",
                target=target,
                error=error or "see logs",
            )
        elif status == "canceled":
            broadcast("build_canceled", url="/jobs", tag=f"job-{job.id}", level="warning", target=target)
        return

    if status == "failed":
        broadcast(
            "operation_failed",
            url="/jobs",
            tag=f"job-{job.id}",
            level="error",
            name=str(getattr(job, "operation_name", "") or "operation"),
            error=error or "see logs",
        )
