import asyncio
import base64
import concurrent.futures
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from . import push as push_service
from . import workspaces as ws_lib
from .avatars import AvatarError, get_avatar
from .build_progress import (
    PROGRESS_CHANNEL as BUILD_PROGRESS_CHANNEL,
)
from .build_progress import (
    clear_progress as clear_build_progress,
)
from .build_progress import (
    list_progress as list_build_progress,
)
from .cleanup import (
    RETENTION_ROM_KEY,
    RETENTION_TARGET_FILES_KEY,
    apply_artifact_retention,
    cleanup_stale_build_overrides,
)
from .config import settings
from .database import Base, SessionLocal, engine, get_db, run_migrations
from .debloat_utils import parse_unica_debloat_entries
from .delta import cached_block_map
from .error_hints import detect_build_hints
from .ff_utils import (
    apply_custom_features,
    is_boolean_feature,
    merge_floating_features,
    normalize_ff_value,
    parse_customize_lists,
    parse_fallback_overrides,
    parse_floating_feature_xml,
    parse_shell_assignments,
    parse_shell_vars,
)
from .firmware_progress import PROGRESS_CHANNEL, clear_progress, list_progress, progress_key
from .job_events import EVENTS_CHANNEL as JOB_EVENTS_CHANNEL
from .job_events import publish as publish_job_event
from .models import AppSetting, BuildJob, PushSubscription, Workspace
from .mods_archive import (
    ModsArchiveError,
    load_upload_meta,
    new_upload_id,
    save_upload_meta,
    upload_archive_path,
    validate_mods_archive,
)
from .mods_utils import parse_unica_mod_entries
from .queue import ARQ_QUEUE_BUILDS, ARQ_QUEUE_CONTROLS, close_arq_pool, get_arq_pool, redis_conn
from .repo_progress import PROGRESS_CHANNEL as REPO_PROGRESS_CHANNEL
from .repo_progress import clear_progress as clear_repo_progress
from .repo_progress import get_progress as get_repo_progress
from .repo_progress import list_progress as list_repo_progress
from .schemas import (
    AdvancedSettingsUpdate,
    BuildJobCreate,
    BuildJobRead,
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    RepoConfigUpdate,
    RetentionUpdate,
    StopJobRequest,
    WorkspaceCreate,
    WorkspaceUpdate,
)
from .workspaces import WorkspaceRef

app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)

_FIRMWARE_LATEST_TIMEOUT_SEC = 10.0
_FIRMWARE_LATEST_TTL_SEC = 3600.0
_FIRMWARE_LATEST_RETRY_SEC = 60.0
_FW_CACHE_KEY_PREFIX = "un1ca:cache:fw_latest:"
_FW_STATS_KEY = "un1ca:cache:fw_latest:stats"
_DIR_SIZE_TTL_SEC = 1200.0
_DIR_CACHE_KEY_PREFIX = "un1ca:cache:dir_size:"
_DIR_STATS_KEY = "un1ca:cache:dir_size:stats"
_REPO_INFO_TTL_SEC = 30.0
_REPO_INFO_KEY_PREFIX = "un1ca:cache:repo_info:v2:"
_GIT_SNAPSHOT_TTL_SEC = 30.0
_GIT_SNAPSHOT_KEY_PREFIX = "un1ca:cache:git_snapshot:v2:"
_HTTP_METRICS_PREFIX = "un1ca:metrics:http:"
_HTTP_LAT_BUCKETS_MS = [10, 25, 50, 100, 200, 350, 500, 750, 1000, 2000, 5000]
_AVATAR_BROWSER_TTL_SEC = 3600.0


_AUTH_CACHE_TTL_SEC = 5.0
_auth_cache: tuple[float, str] = (0.0, "")


def _auth_secret_cached() -> str:
    global _auth_cache
    now = time.time()
    cached_at, secret = _auth_cache
    if now - cached_at <= _AUTH_CACHE_TTL_SEC:
        return secret
    db = SessionLocal()
    try:
        secret = _get_auth_secret(db) if _auth_enabled(db) else ""
    finally:
        db.close()
    _auth_cache = (now, secret)
    return secret


def _invalidate_auth_cache():
    global _auth_cache
    _auth_cache = (0.0, "")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.endswith("/healthz") or path.endswith("/readyz"):
        return await call_next(request)
    if path.startswith(f"{settings.api_prefix}/auth/"):
        return await call_next(request)
    secret = await asyncio.to_thread(_auth_secret_cached)
    if not secret:
        return await call_next(request)
    token = _get_token_from_request(request)
    if not token or not _verify_token(secret, token):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


def _redis_get_json(key: str) -> dict:
    try:
        raw = redis_conn.get(key)
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _redis_set_json(key: str, payload: dict):
    try:
        redis_conn.set(key, json.dumps(payload, ensure_ascii=True))
    except Exception:
        pass


def _redis_hincr(stats_key: str, field: str, amount: int = 1):
    try:
        redis_conn.hincrby(stats_key, field, amount)
    except Exception:
        pass


def _redis_hgetall_int(stats_key: str) -> dict[str, int]:
    try:
        raw = redis_conn.hgetall(stats_key)
    except Exception:
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            val = int(v.decode("utf-8") if isinstance(v, bytes) else str(v))
            out[key] = val
        except Exception:
            continue
    return out


def _redis_count_keys(prefix: str) -> int:
    try:
        return sum(1 for _ in redis_conn.scan_iter(match=f"{prefix}*"))
    except Exception:
        return 0


def _redis_del(key: str):
    try:
        redis_conn.delete(key)
    except Exception:
        pass


def _repo_info_key(workspace_id: str) -> str:
    return f"{_REPO_INFO_KEY_PREFIX}{workspace_id}"


def _git_snapshot_key(workspace_id: str) -> str:
    return f"{_GIT_SNAPSHOT_KEY_PREFIX}{workspace_id}"


def _invalidate_repo_caches(workspace_id: str | None = None):
    if workspace_id:
        _redis_del(_repo_info_key(workspace_id))
        _redis_del(_git_snapshot_key(workspace_id))
        return
    for prefix in (_REPO_INFO_KEY_PREFIX, _GIT_SNAPSHOT_KEY_PREFIX):
        try:
            for key in redis_conn.scan_iter(match=f"{prefix}*"):
                redis_conn.delete(key)
        except Exception:
            pass


async def _enqueue_build(function_name: str, *args) -> str:
    pool = await get_arq_pool()
    queue_job_id = str(uuid.uuid4())
    await pool.enqueue_job(function_name, *args, _job_id=queue_job_id, _queue_name=ARQ_QUEUE_BUILDS)
    return queue_job_id


async def _enqueue_control(function_name: str, *args) -> str:
    pool = await get_arq_pool()
    queue_job_id = str(uuid.uuid4())
    await pool.enqueue_job(function_name, *args, _job_id=queue_job_id, _queue_name=ARQ_QUEUE_CONTROLS)
    return queue_job_id


def _http_metric_key(method: str, route_label: str) -> str:
    return f"{_HTTP_METRICS_PREFIX}{method}:{route_label}"


def _record_http_metric(method: str, route_label: str, status_code: int, latency_ms: float):
    key = _http_metric_key(method, route_label)
    ms = max(0, round(latency_ms))
    bucket_field = "b_inf"
    for bound in _HTTP_LAT_BUCKETS_MS:
        if ms <= bound:
            bucket_field = f"b_{bound}"
            break
    try:
        pipe = redis_conn.pipeline()
        pipe.hincrby(key, "count", 1)
        pipe.hincrby(key, "sum_ms", ms)
        pipe.hincrby(key, bucket_field, 1)
        if status_code >= 500:
            pipe.hincrby(key, "err_5xx", 1)
        pipe.hset(key, "last_status", int(status_code))
        pipe.hset(key, "last_ms", ms)
        pipe.execute()
        redis_conn.expire(key, 7 * 24 * 3600)
    except Exception:
        pass


def _hist_percentile(fields: dict[str, int], q: float) -> int:
    total = int(fields.get("count", 0))
    if total <= 0:
        return 0
    need = max(1, int(total * q))
    seen = 0
    for bound in _HTTP_LAT_BUCKETS_MS:
        seen += int(fields.get(f"b_{bound}", 0))
        if seen >= need:
            return bound
    return _HTTP_LAT_BUCKETS_MS[-1]


def _collect_http_metrics() -> dict[str, dict[str, int | float]]:
    out: dict[str, dict[str, int | float]] = {}
    try:
        keys = list(redis_conn.scan_iter(match=f"{_HTTP_METRICS_PREFIX}*"))
    except Exception:
        return out
    for key in keys:
        raw_key = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        name = raw_key.removeprefix(_HTTP_METRICS_PREFIX)
        try:
            raw = redis_conn.hgetall(raw_key)
        except Exception:
            continue
        fields: dict[str, int] = {}
        for k, v in raw.items():
            kk = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            vv = v.decode("utf-8") if isinstance(v, bytes) else str(v)
            try:
                fields[kk] = int(vv)
            except Exception:
                fields[kk] = 0
        count = int(fields.get("count", 0))
        sum_ms = int(fields.get("sum_ms", 0))
        avg_ms = round(sum_ms / count, 2) if count else 0.0
        out[name] = {
            "count": count,
            "avg_ms": avg_ms,
            "p50_ms": _hist_percentile(fields, 0.50),
            "p95_ms": _hist_percentile(fields, 0.95),
            "last_ms": int(fields.get("last_ms", 0)),
            "last_status": int(fields.get("last_status", 0)),
            "err_5xx": int(fields.get("err_5xx", 0)),
        }
    return out


def _http_metrics_top(limit: int = 10, sort_by: str = "p95") -> list[dict[str, int | float | str]]:
    metrics = _collect_http_metrics()
    key_name = "p95_ms" if sort_by == "p95" else "avg_ms"
    items: list[dict[str, int | float | str]] = []
    for endpoint, values in metrics.items():
        row = {"endpoint": endpoint}
        row.update(values)
        items.append(row)
    items.sort(key=lambda x: float(x.get(key_name, 0.0)), reverse=True)
    return items[: max(1, min(limit, 100))]


# =====================================================================
# Workspace resolution
# =====================================================================


def _require_ws(db: Session, workspace_id: str | None) -> WorkspaceRef:
    ws = ws_lib.get_workspace(db, workspace_id)
    if ws is None:
        raise HTTPException(400, "No workspace configured")
    if workspace_id and ws.id != workspace_id:
        raise HTTPException(404, "Workspace not found")
    ws_lib.ensure_layout(ws)
    return ws_lib.snapshot(ws)


def _require_ws_new_session(workspace_id: str | None) -> WorkspaceRef:
    db = SessionLocal()
    try:
        return _require_ws(db, workspace_id)
    finally:
        db.close()


def _project_root(ws: WorkspaceRef) -> Path | None:
    # Locate the UN1CA root by directory signature so a bind-mount and a volume clone both work
    for root in (ws.root, ws.root / "UN1CA"):
        if (root / "target").is_dir() and (root / "unica" / "configs" / "version.sh").is_file():
            return root
    return None


def _repo_exists(ws: WorkspaceRef) -> bool:
    return (ws.root / ".git").is_dir()


def _read_var_from_shell_file(path: Path, var_name: str) -> str | None:
    # Read plain VAR=... out of shell files without sourcing them
    if not path.exists():
        return None
    pattern = re.compile(rf'^\s*{re.escape(var_name)}\s*=\s*"?([^"\n#]+)"?')
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line.strip())
        if match:
            return match.group(1).strip()
    return None


def _read_int_from_shell_file(path: Path, var_name: str) -> int:
    raw = _read_var_from_shell_file(path, var_name) or ""
    digits = re.match(r"^\d+", raw.strip())
    return int(digits.group(0)) if digits else 0


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    if row and row.value:
        return row.value.strip()
    return default


def _set_setting(db: Session, key: str, value: str):
    row = db.get(AppSetting, key)
    if not row:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def _delete_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row:
        db.delete(row)
        db.commit()


_AUTH_TOKEN_TTL_SEC = 7 * 24 * 3600


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


_PASSWORD_ALGO = "sha512"


def _hash_password(password: str, salt_hex: str, algo: str = _PASSWORD_ALGO) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt, 120_000)
    return digest.hex()


def _get_auth_secret(db: Session) -> str:
    return _get_setting(db, "auth.hash", "")


def _get_auth_salt(db: Session) -> str:
    return _get_setting(db, "auth.salt", "")


def _auth_enabled(db: Session) -> bool:
    return bool(_get_auth_secret(db) and _get_auth_salt(db))


def _make_token(secret_hex: str) -> str:
    payload = {"ts": int(time.time()), "nonce": secrets.token_hex(8)}
    raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    sig = hmac.new(bytes.fromhex(secret_hex), raw, "sha512_256").digest()
    return f"{_b64url_encode(raw)}.{_b64url_encode(sig)}"


def _verify_token(secret_hex: str, token: str) -> bool:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        raw = _b64url_decode(payload_b64)
        expected = hmac.new(bytes.fromhex(secret_hex), raw, "sha512_256").digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return False
        payload = json.loads(raw.decode("utf-8"))
        ts = int(payload.get("ts", 0))
        return (time.time() - ts) <= _AUTH_TOKEN_TTL_SEC
    except Exception:
        return False


def _get_token_from_request(request: Request) -> str:
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.query_params.get("token", "").strip()


def _safe_git_url(url: str) -> str:
    if "@" not in url:
        return url
    if url.startswith("https://"):
        return "https://" + url.split("@", 1)[1]
    if url.startswith("http://"):
        return "http://" + url.split("@", 1)[1]
    return url


def _parse_model_csc(firmware_value: str) -> tuple[str, str]:
    parts = (firmware_value or "").split("/")
    if len(parts) < 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def _require_ws_auth(websocket: WebSocket):
    secret = _auth_secret_cached()
    if not secret:
        return True
    token = websocket.query_params.get("token", "")
    auth = websocket.headers.get("authorization") or websocket.headers.get("Authorization") or ""
    if not token and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    return bool(token and _verify_token(secret, token))


def _get_latest_firmware(model: str, csc: str) -> str:
    # Latest version comes from the Samsung version.xml, behind a TTL cache with a stale fallback
    if not model or not csc:
        return ""
    cache_key = f"{model.upper()}_{csc.upper()}"
    redis_key = f"{_FW_CACHE_KEY_PREFIX}{cache_key}"
    now = time.time()
    cached = _redis_get_json(redis_key)
    if cached:
        cached_value = str(cached.get("value") or "")
        fetched_at = float(cached.get("fetched_at") or 0.0)
        attempted_at = float(cached.get("attempted_at") or 0.0)
        if cached_value and (now - fetched_at) <= _FIRMWARE_LATEST_TTL_SEC:
            _redis_hincr(_FW_STATS_KEY, "hits_fresh")
            return cached_value
        if (now - attempted_at) <= _FIRMWARE_LATEST_RETRY_SEC:
            _redis_hincr(_FW_STATS_KEY, "hits_stale")
            return cached_value
    _redis_hincr(_FW_STATS_KEY, "misses")

    url = f"https://fota-cloud-dn.ospserver.net/firmware/{csc}/{model}/version.xml"
    try:
        with urlopen(url, timeout=_FIRMWARE_LATEST_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        _redis_hincr(_FW_STATS_KEY, "net_ok")
    except (URLError, TimeoutError, OSError):
        _redis_hincr(_FW_STATS_KEY, "net_err")
        if cached:
            return str(cached.get("value") or "")
        _redis_set_json(
            redis_key,
            {
                "value": "",
                "fetched_at": 0.0,
                "attempted_at": now,
            },
        )
        return ""
    m = re.search(r"<latest[^>]*>(.*?)</latest>", body)
    latest = m.group(1).strip() if m else ""
    _redis_set_json(
        redis_key,
        {
            "value": latest,
            "fetched_at": now if latest else 0.0,
            "attempted_at": now,
        },
    )
    return latest


def _dir_size_bytes(path: Path) -> int:
    cache_key = hashlib.new("sha512_256", str(path).encode("utf-8")).hexdigest()[:40]
    redis_key = f"{_DIR_CACHE_KEY_PREFIX}{cache_key}"
    now = time.time()
    cached = _redis_get_json(redis_key)
    if cached and (now - float(cached.get("ts") or 0.0)) <= _DIR_SIZE_TTL_SEC:
        _redis_hincr(_DIR_STATS_KEY, "hits")
        return int(cached.get("size") or 0)
    _redis_hincr(_DIR_STATS_KEY, "misses")

    total = 0
    if not path.exists():
        _redis_set_json(redis_key, {"ts": now, "size": 0})
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    _redis_set_json(redis_key, {"ts": now, "size": total})
    return total


def _collect_resources(ws: WorkspaceRef) -> dict:
    load1, load5, load15 = os.getloadavg()
    mem_total = 0
    mem_available = 0
    try:
        with open("/proc/meminfo", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024
    except Exception:
        pass
    mem_used = max(0, mem_total - mem_available)
    out_usage = shutil.disk_usage(ws.out) if Path(ws.out).exists() else shutil.disk_usage("/")
    data_usage = shutil.disk_usage(settings.data_dir) if Path(settings.data_dir).exists() else shutil.disk_usage("/")
    return {
        "load": {"1m": load1, "5m": load5, "15m": load15},
        "memory": {"total": mem_total, "used": mem_used, "available": mem_available},
        "disk": {
            "out": {"total": out_usage.total, "used": out_usage.used, "free": out_usage.free},
            "data": {"total": data_usage.total, "used": data_usage.used, "free": data_usage.free},
        },
    }


def _empty_fw_row(key: str, model: str, csc: str) -> dict[str, str | int | bool]:
    return {
        "key": key,
        "model": model,
        "csc": csc,
        "odin_version": "",
        "fw_version": "",
        "latest_version": "",
        "odin_size_bytes": 0,
        "fw_size_bytes": 0,
        "has_odin": False,
        "has_fw": False,
    }


def _collect_samsung_fw(ws: WorkspaceRef) -> dict[str, list[dict[str, str | int | bool]]]:
    # Fold the Odin/FW cache into a single card list keyed by MODEL_CSC
    out_root = Path(ws.out)
    odin_root = out_root / "odin"
    fw_root = out_root / "fw"
    rows: dict[str, dict[str, str | int | bool]] = {}

    if odin_root.is_dir():
        for d in sorted([x for x in odin_root.iterdir() if x.is_dir()], key=lambda x: x.name):
            model, csc = (*d.name.split("_", 1), "")[:2] if "_" in d.name else (d.name, "")
            key = f"{model}_{csc}" if csc else model
            rows.setdefault(key, _empty_fw_row(key, model, csc))
            rows[key]["has_odin"] = True
            rows[key]["odin_size_bytes"] = _dir_size_bytes(d)
            marker = d / ".downloaded"
            if marker.exists():
                rows[key]["odin_version"] = marker.read_text(encoding="utf-8", errors="ignore").strip()

    if fw_root.is_dir():
        for d in sorted([x for x in fw_root.iterdir() if x.is_dir()], key=lambda x: x.name):
            model, csc = (*d.name.split("_", 1), "")[:2] if "_" in d.name else (d.name, "")
            key = f"{model}_{csc}" if csc else model
            rows.setdefault(key, _empty_fw_row(key, model, csc))
            rows[key]["has_fw"] = True
            rows[key]["fw_size_bytes"] = _dir_size_bytes(d)
            marker = d / ".extracted"
            if marker.exists():
                rows[key]["fw_version"] = marker.read_text(encoding="utf-8", errors="ignore").strip()

    return {"items": sorted(rows.values(), key=lambda x: str(x.get("key", "")))}


def _fill_latest_for_fw_items(items: list[dict[str, str | int | bool]]):
    # Resolve latest firmware in parallel to avoid N sequential network waits on first load
    pairs: list[tuple[str, str]] = []
    for item in items:
        model = str(item.get("model") or "")
        csc = str(item.get("csc") or "")
        if model and csc:
            pairs.append((model, csc))
    uniq = sorted(set(pairs))
    if not uniq:
        return
    latest_map: dict[tuple[str, str], str] = {}
    max_workers = min(8, max(2, len(uniq)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map = {pool.submit(_get_latest_firmware, model, csc): (model, csc) for model, csc in uniq}
        for fut in concurrent.futures.as_completed(fut_map):
            model, csc = fut_map[fut]
            try:
                latest_map[(model, csc)] = fut.result()
            except Exception:
                latest_map[(model, csc)] = ""
    for item in items:
        model = str(item.get("model") or "")
        csc = str(item.get("csc") or "")
        item["latest_version"] = latest_map.get((model, csc), "")


def _make_firmware_status(firmware_value: str, cache_items: list[dict[str, str | int | bool]]) -> dict[str, str | bool]:
    # Status payload for the source/target cards, including the up_to_date flag
    model, csc = _parse_model_csc(firmware_value)
    key = f"{model}_{csc}" if model and csc else ""
    entry = next((x for x in cache_items if x.get("key") == key), None)
    latest = str(entry.get("latest_version") or "") if entry else _get_latest_firmware(model, csc)
    downloaded = str(entry.get("odin_version")) if entry and entry.get("odin_version") else ""
    extracted = str(entry.get("fw_version")) if entry and entry.get("fw_version") else ""
    return {
        "source_model": model,
        "source_csc": csc,
        "latest_version": latest,
        "downloaded_version": downloaded,
        "extracted_version": extracted,
        "up_to_date": bool(latest and (downloaded == latest or extracted == latest)),
    }


def _parse_targets_override(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[\s,]+", value.strip())
    return [p for p in (x.strip() for x in parts) if p]


def _get_targets_detected(ws: WorkspaceRef) -> list[str]:
    project_root = _project_root(ws)
    if not project_root:
        return []
    root = project_root / "target"
    if not root.is_dir():
        return []
    return sorted([d.name for d in root.iterdir() if d.is_dir()])


def _get_targets(ws: WorkspaceRef) -> list[str]:
    override = _parse_targets_override(ws.targets_override)
    if override:
        return override
    return _get_targets_detected(ws)


def _get_target_options(ws: WorkspaceRef) -> list[dict[str, str]]:
    override = _parse_targets_override(ws.targets_override)
    root = _project_root(ws)
    if not root:
        if override:
            return [{"code": code, "name": code} for code in override]
        return []
    options = []
    if override:
        for code in override:
            cfg = root / "target" / code / "config.sh"
            target_name = _read_var_from_shell_file(cfg, "TARGET_NAME") or code
            options.append({"code": code, "name": target_name})
    else:
        for d in sorted([x for x in (root / "target").iterdir() if x.is_dir()], key=lambda x: x.name):
            target_name = _read_var_from_shell_file(d / "config.sh", "TARGET_NAME") or d.name
            options.append({"code": d.name, "name": target_name})
    return options


def _repo_capabilities(ws: WorkspaceRef) -> dict[str, bool]:
    # Forks of the firmware sources differ in what their build scripts accept, so
    # the panel asks the checkout instead of assuming its own upstream
    root = _project_root(ws) or Path(ws.root)

    def offers(rel: str, flag: str) -> bool:
        try:
            return flag in (root / rel).read_text(errors="ignore")
        except OSError:
            return False

    return {
        "incremental_zip": offers("scripts/build_flashable_zip.sh", "--incremental"),
        "incremental_from_dir": offers("scripts/build_flashable_zip.sh", "<file|dir>"),
        "rom_zip": offers("scripts/make_rom.sh", "--build-rom-zip"),
        "skip_target_files": offers("scripts/make_rom.sh", "--no-target-files"),
        "dsu_package": (root / "scripts" / "internal" / "create_target_files_zip.sh").is_file(),
        "delta_zstd": bool(shutil.which("zstd")),
    }


def _get_defaults_for_target(ws: WorkspaceRef, target: str) -> dict[str, str | int]:
    root = _project_root(ws) or Path(ws.root)
    preferred = _preferred_source_configs_for_target(root, target)
    source_firmware = _read_source_firmware_from_configs(root, ws.source_config_override, preferred)
    target_firmware = _read_var_from_shell_file(root / "target" / target / "config.sh", "TARGET_FIRMWARE") or ""
    version_path = root / "unica" / "configs" / "version.sh"
    return {
        "source_firmware": source_firmware,
        "target_firmware": target_firmware,
        "version_major": _read_int_from_shell_file(version_path, "VERSION_MAJOR"),
        "version_minor": _read_int_from_shell_file(version_path, "VERSION_MINOR"),
        "version_patch": _read_int_from_shell_file(version_path, "VERSION_PATCH"),
        "version_suffix": "",
    }


def _read_source_firmware_from_configs(
    root: Path,
    override: str | None = None,
    preferred: list[str] | None = None,
) -> str:
    value, _ = _read_source_firmware_from_configs_with_source(root, override, preferred)
    return value


def _read_source_firmware_from_configs_with_source(
    root: Path,
    override: str | None = None,
    preferred: list[str] | None = None,
) -> tuple[str, str]:
    configs_dir = root / "unica" / "configs"
    if override:
        override_name = override.strip()
        if override_name:
            value = _read_var_from_shell_file(configs_dir / override_name, "SOURCE_FIRMWARE")
            if value:
                return value, override_name
    preferred_list = [x for x in (preferred or []) if x]
    if preferred_list:
        for name in preferred_list:
            value = _read_var_from_shell_file(configs_dir / name, "SOURCE_FIRMWARE")
            if value:
                return value, name
    fallback = ["essi.sh", "essi_64.sh", "qssi.sh", "mssi.sh"]
    for name in fallback:
        value = _read_var_from_shell_file(configs_dir / name, "SOURCE_FIRMWARE")
        if value:
            return value, name
    if configs_dir.is_dir():
        for cfg in sorted(configs_dir.glob("*.sh")):
            if cfg.name == "version.sh":
                continue
            value = _read_var_from_shell_file(cfg, "SOURCE_FIRMWARE")
            if value:
                return value, cfg.name
    return "", ""


def _preferred_source_configs_for_target(root: Path, target: str) -> list[str]:
    if not target:
        return []
    cfg_path = root / "target" / target / "config.sh"
    value = _read_var_from_shell_file(cfg_path, "TARGET_SINGLE_SYSTEM_IMAGE")
    if not value:
        return []
    key = value.strip().strip('"').strip("'").lower()
    if not key:
        return []
    if key.endswith(".sh"):
        return [key]
    alias = {
        "essi": ["essi.sh", "essi_64.sh"],
        "essi_64": ["essi_64.sh", "essi.sh"],
        "qssi": ["qssi.sh"],
        "mssi": ["mssi.sh"],
    }
    return alias.get(key, [f"{key}.sh"])


def _list_config_candidates(root: Path) -> list[dict[str, str | bool]]:
    configs_dir = root / "unica" / "configs"
    if not configs_dir.is_dir():
        return []
    entries: list[dict[str, str | bool]] = []
    for cfg in sorted(configs_dir.glob("*.sh")):
        if cfg.name == "version.sh":
            continue
        has_value = bool(_read_var_from_shell_file(cfg, "SOURCE_FIRMWARE"))
        entries.append({"name": cfg.name, "has_source_firmware": has_value})
    return entries


def _firmware_path_from_value(value: str) -> str:
    parts = (value or "").split("/")
    if len(parts) < 2:
        return ""
    model = parts[0].strip()
    csc = parts[1].strip()
    if not model or not csc:
        return ""
    return f"{model}_{csc}"


def _collect_ff_defaults(
    ws: WorkspaceRef,
    target: str,
    source_firmware: str,
    target_firmware: str,
) -> dict[str, object]:
    root = _project_root(ws) or Path(ws.root)
    out_root = Path(ws.out)
    source_key = _firmware_path_from_value(source_firmware)
    target_key = _firmware_path_from_value(target_firmware)
    fallback_xml = Path(__file__).resolve().parents[2] / "floating_feature.xml"

    source_xml = out_root / "fw" / source_key / "system/system/etc/floating_feature.xml"
    target_xml = out_root / "fw" / target_key / "system/system/etc/floating_feature.xml"
    if not source_xml.exists():
        source_xml = fallback_xml
    if not target_xml.exists():
        target_xml = fallback_xml

    source_entries = parse_floating_feature_xml(source_xml)
    target_entries = parse_floating_feature_xml(target_xml)

    customize_path = root / "unica" / "patches" / "__floating_feature" / "customize.sh"
    lists = parse_customize_lists(customize_path)

    target_vars = parse_shell_vars(root / "target" / target / "config.sh")
    platform = target_vars.get("TARGET_PLATFORM")
    if platform:
        target_vars.update(parse_shell_vars(root / "platform" / platform / "config.sh"))
    fallback_overrides = parse_fallback_overrides(customize_path, target_vars)

    merged = merge_floating_features(
        source_entries,
        target_entries,
        lists["deprecated"],
        lists["blacklist"],
        fallback_overrides,
    )

    platform_sff = OrderedDict()
    if platform:
        platform_sff = parse_shell_assignments(root / "platform" / platform / "sff.sh")
    device_sff = parse_shell_assignments(root / "target" / target / "sff.sh")
    merged = apply_custom_features(merged, platform_sff)
    merged = apply_custom_features(merged, device_sff)

    entries = []
    for key, value in merged.items():
        entries.append(
            {
                "key": key,
                "value": value,
                "is_boolean": is_boolean_feature(value),
            }
        )

    return {
        "entries": entries,
        "source_path": str(source_xml),
        "target_path": str(target_xml),
    }


def _build_signature(
    workspace_id: str,
    target: str,
    source_commit: str,
    source_firmware: str,
    target_firmware: str,
    version_major: int,
    version_minor: int,
    version_patch: int,
    version_suffix: str,
    extra_mods_signature: str,
    debloat_signature: str,
    debloat_add_system_signature: str,
    debloat_add_product_signature: str,
    mods_signature: str,
    ff_signature: str,
) -> str:
    # The build signature is what lets an identical request reuse an existing ZIP
    payload = "|".join(
        [
            workspace_id,
            target,
            source_commit,
            source_firmware,
            target_firmware,
            str(version_major),
            str(version_minor),
            str(version_patch),
            version_suffix,
            extra_mods_signature,
            debloat_signature,
            debloat_add_system_signature,
            debloat_add_product_signature,
            mods_signature,
            ff_signature,
        ]
    )
    return hashlib.new("sha512_256", payload.encode("utf-8")).hexdigest()[:40]


def _git_text(root: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", "safe.directory=*", "-C", str(root), *args],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _resolve_source_commit(ws: WorkspaceRef) -> str:
    # Git objects to directory ownership inside the container, hence safe.directory=* everywhere
    root = _project_root(ws)
    if not root:
        return settings.source_commit or "unknown"
    return _git_text(root, ["rev-parse", "--short", "HEAD"]) or (settings.source_commit or "unknown")


def _empty_commit_details() -> dict[str, str]:
    return {
        "branch": "",
        "short_hash": settings.source_commit or "unknown",
        "full_hash": "",
        "subject": "",
        "body": "",
        "author_name": "",
        "author_email": "",
        "committer_name": "",
        "committer_email": "",
    }


def _resolve_commit_details(ws: WorkspaceRef) -> dict[str, str]:
    # Commit detail shown on the repository screen
    root = _project_root(ws)
    if not root:
        return _empty_commit_details()
    branch = _git_text(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    fmt = "%H%n%h%n%s%n%b%n%an%n%ae%n%cn%n%ce"
    raw = _git_text(root, ["log", "-1", f"--pretty={fmt}"])
    if not raw:
        details = _empty_commit_details()
        details["branch"] = branch
        return details
    parts = raw.split("\n")
    full_hash = parts[0].strip() if len(parts) > 0 else ""
    short_hash = parts[1].strip() if len(parts) > 1 else (settings.source_commit or "unknown")
    subject = parts[2].strip() if len(parts) > 2 else ""
    author_name = parts[-4].strip() if len(parts) >= 4 else ""
    author_email = parts[-3].strip() if len(parts) >= 3 else ""
    committer_name = parts[-2].strip() if len(parts) >= 2 else ""
    committer_email = parts[-1].strip() if len(parts) >= 1 else ""
    body = "\n".join(parts[3:-4]).strip() if len(parts) > 7 else ""
    return {
        "branch": branch,
        "short_hash": short_hash,
        "full_hash": full_hash,
        "subject": subject,
        "body": body,
        "author_name": author_name,
        "author_email": author_email,
        "committer_name": committer_name,
        "committer_email": committer_email,
    }


def _repo_sync_status(root: Path | None, branch: str) -> dict[str, str | int]:
    # ahead/behind against origin/<branch> drives the sync badge in the UI
    if not root or not branch or branch == "HEAD":
        return {"state": "unknown", "ahead_by": 0, "behind_by": 0, "remote_ref": ""}
    remote_ref = f"origin/{branch}"
    try:
        has_remote = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(root), "rev-parse", "--verify", remote_ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if has_remote.returncode != 0:
            return {"state": "unknown", "ahead_by": 0, "behind_by": 0, "remote_ref": remote_ref}

        counts = subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=*",
                "-C",
                str(root),
                "rev-list",
                "--left-right",
                "--count",
                f"HEAD...{remote_ref}",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        left, right = (*counts.split(), "0", "0")[:2]
        ahead_by = int(left)
        behind_by = int(right)
        if ahead_by == 0 and behind_by == 0:
            state = "up_to_date"
        elif ahead_by == 0 and behind_by > 0:
            state = "behind"
        elif ahead_by > 0 and behind_by == 0:
            state = "ahead"
        else:
            state = "diverged"
        return {"state": state, "ahead_by": ahead_by, "behind_by": behind_by, "remote_ref": remote_ref}
    except Exception:
        return {"state": "unknown", "ahead_by": 0, "behind_by": 0, "remote_ref": remote_ref}


def _git_snapshot_cached(ws: WorkspaceRef) -> dict[str, dict]:
    cache_key = _git_snapshot_key(ws.id)
    cached = _redis_get_json(cache_key)
    if cached and isinstance(cached.get("commit"), dict) and isinstance(cached.get("repo_sync"), dict):
        return cached
    if not _repo_exists(ws):
        payload = {
            "commit": _empty_commit_details(),
            "repo_sync": {"state": "unknown", "ahead_by": 0, "behind_by": 0, "remote_ref": ""},
        }
    else:
        commit_details = _resolve_commit_details(ws)
        repo_sync = _repo_sync_status(_project_root(ws), str(commit_details.get("branch") or ""))
        payload = {"commit": commit_details, "repo_sync": repo_sync}
    _redis_set_json(cache_key, payload)
    try:
        redis_conn.expire(cache_key, int(_GIT_SNAPSHOT_TTL_SEC))
    except Exception:
        pass
    return payload


def _repo_info(ws: WorkspaceRef) -> dict[str, str | int | bool | dict]:
    cache_key = _repo_info_key(ws.id)
    cached = _redis_get_json(cache_key)
    if cached and isinstance(cached.get("git_url"), str):
        cached["progress"] = get_repo_progress(ws.id)
        return cached

    snapshot = _git_snapshot_cached(ws)
    payload = {
        "workspace_id": ws.id,
        "git_url": ws.git_url,
        "git_ref": ws.git_ref,
        "repo_path": str(ws.root),
        "repo_exists": _repo_exists(ws),
        "repo_size_bytes": _dir_size_bytes(Path(ws.root)),
        "git_username": ws.git_username,
        "git_token_set": bool(ws.git_token),
        "commit": snapshot.get("commit", {}),
        "repo_sync": snapshot.get("repo_sync", {}),
    }
    _redis_set_json(cache_key, payload)
    try:
        redis_conn.expire(cache_key, int(_REPO_INFO_TTL_SEC))
    except Exception:
        pass
    payload["progress"] = get_repo_progress(ws.id)
    return payload


def _normalize_path_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = (raw or "").strip()
        if not item or item in seen:
            continue
        # Keep this simple: debloat values are plain partition-relative paths
        if any(ch in item for ch in ("\n", "\r", '"')):
            raise HTTPException(400, f"Invalid debloat path: {item!r}")
        out.append(item)
        seen.add(item)
    return out


@app.on_event("startup")
async def on_startup():
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.logs_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    run_migrations()
    db = SessionLocal()
    try:
        ws_lib.bootstrap(db)
        for ws in ws_lib.list_workspaces(db):
            ws_lib.ensure_layout(ws)
    finally:
        db.close()
    cleaned = await asyncio.to_thread(cleanup_stale_build_overrides)
    # Progress lives in Redis and outlives the processes that wrote it; a fresh
    # boot means nothing is running, so start from an empty board
    clear_progress()
    clear_repo_progress()
    clear_build_progress()
    _invalidate_repo_caches()
    await get_arq_pool()
    print(
        f"[startup] cleanup: removed {cleaned['uploaded_mod_dirs']} uploaded mod override dirs, "
        f"{cleaned['tmp_extra_mods_dirs']} temp extra-mod dirs, "
        f"{cleaned['stale_clone_dirs']} stale clone dirs",
        flush=True,
    )


@app.on_event("shutdown")
async def on_shutdown():
    await close_arq_pool()


app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def http_perf_metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = int(getattr(response, "status_code", 200))
        return response
    finally:
        route = request.scope.get("route")
        route_label = getattr(route, "path", None) or request.url.path
        _record_http_metric(request.method, str(route_label), status_code, (time.perf_counter() - started) * 1000.0)


def _target_has_latest_artifact(db: Session, workspace_id: str, target: str) -> bool:
    # The Latest ZIP button may only light up when the file is really on disk
    if not target:
        return False
    job = (
        db.query(BuildJob)
        .filter(
            BuildJob.workspace_id == workspace_id,
            BuildJob.target == target,
            BuildJob.status.in_(("succeeded", "reused")),
            BuildJob.artifact_path.isnot(None),
        )
        .order_by(desc(BuildJob.finished_at), desc(BuildJob.created_at))
        .first()
    )
    if not job or not job.artifact_path:
        return False
    return Path(job.artifact_path).exists()


def _target_has_latest_artifact_with_new_session(workspace_id: str, target: str) -> bool:
    db = SessionLocal()
    try:
        return _target_has_latest_artifact(db, workspace_id, target)
    finally:
        db.close()


def _list_jobs_with_new_session(workspace_id: str | None, limit: int) -> list[BuildJob]:
    db = SessionLocal()
    try:
        q = db.query(BuildJob)
        if workspace_id:
            q = q.filter(BuildJob.workspace_id == workspace_id)
        return q.order_by(desc(BuildJob.created_at)).limit(min(max(limit, 1), 200)).all()
    finally:
        db.close()


def _get_job_with_new_session(job_id: str) -> BuildJob | None:
    db = SessionLocal()
    try:
        return db.get(BuildJob, job_id)
    finally:
        db.close()


def _get_job_artifact_path_with_new_session(job_id: str) -> Path:
    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job or not job.artifact_path:
            raise HTTPException(404, "Artifact not found")
        p = Path(job.artifact_path)
        if not p.exists():
            raise HTTPException(404, "Artifact file is missing")
        return p
    finally:
        db.close()


def _get_latest_artifact_path_for_target(workspace_id: str, target: str) -> Path:
    db = SessionLocal()
    try:
        job = (
            db.query(BuildJob)
            .filter(
                BuildJob.workspace_id == workspace_id,
                BuildJob.target == target,
                BuildJob.status.in_(("succeeded", "reused")),
                BuildJob.artifact_path.isnot(None),
            )
            .order_by(desc(BuildJob.finished_at), desc(BuildJob.created_at))
            .first()
        )
        if not job or not job.artifact_path:
            raise HTTPException(404, "Latest artifact not found for target")
        p = Path(job.artifact_path)
        if not p.exists():
            raise HTTPException(404, "Artifact file is missing")
        return p
    finally:
        db.close()


def _list_artifacts_with_new_session(workspace_id: str, target: str | None = None, limit: int = 50) -> list[dict]:
    db = SessionLocal()
    try:
        q = (
            db.query(BuildJob)
            .filter(
                BuildJob.workspace_id == workspace_id,
                BuildJob.artifact_path.isnot(None),
                BuildJob.status.in_(("succeeded", "reused")),
            )
            .order_by(desc(BuildJob.finished_at), desc(BuildJob.created_at))
        )
        if target:
            q = q.filter(BuildJob.target == target)
        rows = q.limit(max(1, min(limit, 200))).all()
        items = []
        for job in rows:
            size = 0
            exists = bool(job.artifact_path and Path(job.artifact_path).exists())
            if exists:
                size = Path(job.artifact_path).stat().st_size
            target_files = Path(str(job.target_files_path)) if job.target_files_path else None
            target_files_exists = bool(target_files and target_files.is_file())
            items.append(
                {
                    "job_id": job.id,
                    "target": job.target,
                    "artifact_path": job.artifact_path,
                    "size_bytes": size,
                    "exists": exists,
                    "target_files_exists": target_files_exists,
                    "target_files_size": target_files.stat().st_size if target_files_exists else 0,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "source_commit": job.source_commit,
                    "version_major": job.version_major,
                    "version_minor": job.version_minor,
                    "version_patch": job.version_patch,
                    "version_suffix": job.version_suffix,
                    "reused_from_job_id": job.reused_from_job_id,
                }
            )
        return items
    finally:
        db.close()


def _readyz_impl() -> dict:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        redis_conn.ping()
    finally:
        db.close()
    return {"status": "ready"}


@app.get(f"{settings.api_prefix}/healthz")
async def healthz():
    # Liveness only. Dependency state belongs in readyz: a check that goes
    # through the thread pool reports a busy process as a dead one
    return {"status": "ok"}


@app.get(f"{settings.api_prefix}/readyz")
async def readyz():
    try:
        return await asyncio.to_thread(_readyz_impl)
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "down", "reason": str(exc)})


@app.get(f"{settings.api_prefix}/auth/status")
async def auth_status(db: Session = Depends(get_db)):
    return {"enabled": _auth_enabled(db)}


@app.post(f"{settings.api_prefix}/auth/login")
async def auth_login(payload: dict, db: Session = Depends(get_db)):
    password = str(payload.get("password") or "")
    if not password:
        raise HTTPException(400, "Password required")
    if not _auth_enabled(db):
        raise HTTPException(400, "Auth is not enabled yet")
    salt = _get_auth_salt(db)
    secret = _get_auth_secret(db)
    # A password stored before the move to sha512 still verifies under the
    # algorithm it was made with, and is rewritten the first time it is used
    stored_algo = _get_setting(db, "auth.algo", "sha256")
    if not hmac.compare_digest(_hash_password(password, salt, stored_algo), secret):
        raise HTTPException(401, "Invalid password")
    if stored_algo != _PASSWORD_ALGO:
        secret = _hash_password(password, salt)
        _set_setting(db, "auth.hash", secret)
        _set_setting(db, "auth.algo", _PASSWORD_ALGO)
        _invalidate_auth_cache()
    return {"token": _make_token(secret)}


@app.post(f"{settings.api_prefix}/auth/password")
async def auth_set_password(payload: dict, request: Request, db: Session = Depends(get_db)):
    password = str(payload.get("password") or "")
    if _auth_enabled(db):
        token = _get_token_from_request(request)
        if not token or not _verify_token(_get_auth_secret(db), token):
            raise HTTPException(401, "Unauthorized")
    if not password:
        _delete_setting(db, "auth.hash")
        _delete_setting(db, "auth.salt")
        _invalidate_auth_cache()
        return {"enabled": False}
    salt = secrets.token_hex(16)
    hashed = _hash_password(password, salt)
    _set_setting(db, "auth.salt", salt)
    _set_setting(db, "auth.hash", hashed)
    _set_setting(db, "auth.algo", _PASSWORD_ALGO)
    _invalidate_auth_cache()
    return {"enabled": True, "token": _make_token(hashed)}


# =====================================================================
# Workspaces
# =====================================================================


@app.get(f"{settings.api_prefix}/workspaces")
async def list_workspaces(db: Session = Depends(get_db)):
    rows = ws_lib.list_workspaces(db)
    return {
        "items": [ws_lib.serialize(ws) for ws in rows],
        "default_id": rows[0].id if rows else "",
        "workspaces_root": str(ws_lib.workspaces_root()),
        "shared_cache_root": str(ws_lib.shared_cache_root()),
    }


@app.post(f"{settings.api_prefix}/workspaces")
async def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)):
    url = (payload.git_url or "").strip()
    if not re.match(r"^(https://|git@|ssh://).+", url):
        raise HTTPException(400, "Invalid git url")
    ws = ws_lib.create_workspace(
        db,
        name=payload.name,
        git_url=url,
        git_ref=payload.git_ref or settings.repo_ref_default,
        git_username=payload.git_username or "",
        git_token=payload.git_token or "",
        shared_fw_cache=payload.shared_fw_cache,
    )
    data = ws_lib.serialize(ws)
    if payload.clone_now:
        op_job = _create_operation_job(
            db,
            workspace_id=ws.id,
            target="repo",
            operation_name=f"Repo clone: {_safe_git_url(url)}",
        )
        op_job.queue_job_id = await _enqueue_build("repo_clone_job_task", op_job.id, False)
        db.commit()
        data["clone_job_id"] = op_job.id
    return data


@app.patch(f"{settings.api_prefix}/workspaces/{{workspace_id}}")
async def update_workspace(workspace_id: str, payload: WorkspaceUpdate, db: Session = Depends(get_db)):
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if payload.name is not None:
        ws.name = payload.name.strip() or ws.name
    if payload.git_url is not None:
        url = payload.git_url.strip()
        if not re.match(r"^(https://|git@|ssh://).+", url):
            raise HTTPException(400, "Invalid git url")
        ws.git_url = url
    if payload.git_ref is not None:
        ws.git_ref = payload.git_ref.strip() or ws.git_ref
    if payload.git_username is not None:
        ws.git_username = payload.git_username.strip()
    if payload.git_token is not None:
        ws.git_token = payload.git_token.strip()
    if payload.shared_fw_cache is not None:
        ws.shared_fw_cache = bool(payload.shared_fw_cache)
    db.commit()
    db.refresh(ws)
    # Toggling the shared cache rewires out/odin and out/fw, moving any local
    # cache into the shared tree on the way
    await asyncio.to_thread(ws_lib.ensure_layout, ws)
    _invalidate_repo_caches(ws.id)
    return ws_lib.serialize(ws)


@app.delete(f"{settings.api_prefix}/workspaces/{{workspace_id}}", response_model=BuildJobRead)
async def delete_workspace(workspace_id: str, delete_files: bool = False, db: Session = Depends(get_db)):
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if db.query(Workspace).count() <= 1:
        raise HTTPException(400, "Cannot delete the last workspace")
    running = (
        db.query(BuildJob)
        .filter(BuildJob.workspace_id == workspace_id, BuildJob.status.in_(("queued", "running")))
        .count()
    )
    if running:
        raise HTTPException(409, "Workspace has running jobs, stop them first")

    remaining = [x for x in ws_lib.list_workspaces(db) if x.id != workspace_id]
    host = remaining[0]
    op_job = _create_operation_job(
        db,
        workspace_id=host.id,
        target="repo",
        operation_name=f"Delete workspace: {ws.name}",
    )
    op_job.queue_job_id = await _enqueue_build("workspace_delete_job_task", op_job.id, workspace_id, delete_files)
    db.delete(ws)
    db.commit()
    db.refresh(op_job)
    clear_repo_progress(workspace_id)
    _invalidate_repo_caches(workspace_id)
    return op_job


@app.get(f"{settings.api_prefix}/push/config")
async def push_config(db: Session = Depends(get_db)):
    public = await asyncio.to_thread(push_service.public_key)
    return {"public_key": public, "subscriptions": db.query(PushSubscription).count()}


@app.post(f"{settings.api_prefix}/push/subscriptions")
async def push_subscribe(payload: PushSubscriptionCreate, db: Session = Depends(get_db)):
    p256dh = payload.keys.get("p256dh", "")
    auth = payload.keys.get("auth", "")
    if not p256dh or not auth:
        raise HTTPException(400, "Subscription keys are missing")
    row = db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    if row is None:
        row = PushSubscription(endpoint=payload.endpoint)
        db.add(row)
    row.p256dh = p256dh
    row.auth = auth
    row.language = (payload.language or "en")[:8]
    db.commit()
    return {"ok": True}


@app.delete(f"{settings.api_prefix}/push/subscriptions")
async def push_unsubscribe(payload: PushSubscriptionDelete, db: Session = Depends(get_db)):
    db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).delete()
    db.commit()
    return {"ok": True}


@app.post(f"{settings.api_prefix}/push/test")
async def push_test(language: str = "en"):
    await asyncio.to_thread(push_service.broadcast, "test", "/build", "test", "info")
    return {"ok": True}


@app.get(f"{settings.api_prefix}/debug/perf")
async def debug_perf():
    fw_stats, dir_stats, http_metrics = await asyncio.gather(
        asyncio.to_thread(_redis_hgetall_int, _FW_STATS_KEY),
        asyncio.to_thread(_redis_hgetall_int, _DIR_STATS_KEY),
        asyncio.to_thread(_collect_http_metrics),
    )
    return {
        "firmware_latest_cache": {
            "storage": "redis",
            "entries": _redis_count_keys(_FW_CACHE_KEY_PREFIX),
            "ttl_sec": _FIRMWARE_LATEST_TTL_SEC,
            "retry_sec": _FIRMWARE_LATEST_RETRY_SEC,
            "timeout_sec": _FIRMWARE_LATEST_TIMEOUT_SEC,
            "hits_fresh": fw_stats.get("hits_fresh", 0),
            "hits_stale": fw_stats.get("hits_stale", 0),
            "misses": fw_stats.get("misses", 0),
            "net_ok": fw_stats.get("net_ok", 0),
            "net_err": fw_stats.get("net_err", 0),
        },
        "dir_size_cache": {
            "storage": "redis",
            "entries": _redis_count_keys(_DIR_CACHE_KEY_PREFIX),
            "ttl_sec": _DIR_SIZE_TTL_SEC,
            "hits": dir_stats.get("hits", 0),
            "misses": dir_stats.get("misses", 0),
        },
        "repo_cache": {
            "storage": "redis",
            "repo_info_ttl_sec": _REPO_INFO_TTL_SEC,
            "git_snapshot_ttl_sec": _GIT_SNAPSHOT_TTL_SEC,
            "repo_info_cached": _redis_count_keys(_REPO_INFO_KEY_PREFIX),
            "git_snapshot_cached": _redis_count_keys(_GIT_SNAPSHOT_KEY_PREFIX),
        },
        "http_metrics": {
            "storage": "redis",
            "endpoints": http_metrics,
        },
    }


@app.get(f"{settings.api_prefix}/avatars/{{username}}")
async def avatar(username: str, size: int = 88):
    # Proxied and cached on disk: GitHub only allows a five minute cache and
    # answers the redirect with no-cache, so the About screen would hit the
    # network on every open and show nothing at all when offline
    try:
        body, content_type = await asyncio.to_thread(get_avatar, username, size)
    except AvatarError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": f"max-age={int(_AVATAR_BROWSER_TTL_SEC)}"},
    )


@app.get(f"{settings.api_prefix}/system/resources")
async def system_resources(workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    return await asyncio.to_thread(_collect_resources, ws)


@app.websocket(f"{settings.api_prefix}/system/resources/ws")
async def stream_resources_ws(websocket: WebSocket, workspace: str | None = None):
    # Load, memory and disk only change by being sampled, so the ticker lives
    # here and the client just listens
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    try:
        ws = await asyncio.to_thread(_require_ws_new_session, workspace)
    except HTTPException:
        await websocket.close(code=4404)
        return
    try:
        while True:
            payload = await asyncio.to_thread(_collect_resources, ws)
            await websocket.send_json(payload)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass


@app.get(f"{settings.api_prefix}/debug/perf/top")
async def debug_perf_top(limit: int = 10, sort_by: str = "p95"):
    if sort_by not in {"p95", "avg"}:
        raise HTTPException(400, "sort_by must be p95 or avg")
    top = await asyncio.to_thread(_http_metrics_top, limit, sort_by)
    return {"sort_by": sort_by, "limit": max(1, min(limit, 100)), "items": top}


def _create_operation_job(db: Session, *, workspace_id: str, target: str, operation_name: str) -> BuildJob:
    # Operation jobs (extract/delete/repo) share the jobs list so the UI stays uniform
    job = BuildJob(
        workspace_id=workspace_id,
        job_kind="operation",
        operation_name=operation_name,
        target=target,
        source_commit="unknown",
        force=False,
        no_rom_zip=False,
        skip_target_files=False,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    publish_job_event(job)
    return job


@app.post(f"{settings.api_prefix}/jobs", response_model=BuildJobRead)
async def create_job(payload: BuildJobCreate, workspace: str | None = None, db: Session = Depends(get_db)):
    # Main build entry point: defaults -> signature -> reuse an artifact or queue a new build
    ws = _require_ws(db, workspace)
    source_commit = _resolve_source_commit(ws)
    if payload.target not in _get_targets(ws):
        raise HTTPException(400, "Unknown target")
    defaults = _get_defaults_for_target(ws, payload.target)
    source_firmware = payload.source_firmware or str(defaults["source_firmware"])
    target_firmware = payload.target_firmware or str(defaults["target_firmware"])
    version_major = payload.version_major if payload.version_major is not None else int(defaults["version_major"])
    version_minor = payload.version_minor if payload.version_minor is not None else int(defaults["version_minor"])
    version_patch = payload.version_patch if payload.version_patch is not None else int(defaults["version_patch"])
    version_suffix = (
        payload.version_suffix if payload.version_suffix is not None else str(defaults["version_suffix"])
    ).strip()

    mods_disabled = payload.mods_disabled
    mods_disabled_json = None
    mods_signature = ""
    if mods_disabled is not None:
        valid_mod_ids = {x["id"] for x in parse_unica_mod_entries(_project_root(ws) or Path(ws.root))}
        unknown_mods = [x for x in mods_disabled if x not in valid_mod_ids]
        if unknown_mods:
            raise HTTPException(400, f"Unknown mod ids: {', '.join(unknown_mods[:5])}")
        mods_disabled_json = json.dumps(sorted(set(mods_disabled)), ensure_ascii=True)
        mods_signature = hashlib.new("sha512_256", mods_disabled_json.encode("utf-8")).hexdigest()[:16]

    debloat_disabled = payload.debloat_disabled or []
    valid_debloat_ids = {x["id"] for x in parse_unica_debloat_entries(_project_root(ws) or Path(ws.root))}
    if debloat_disabled:
        unknown = [x for x in debloat_disabled if x not in valid_debloat_ids]
        if unknown:
            raise HTTPException(400, f"Unknown debloat ids: {', '.join(unknown[:5])}")
    debloat_add_system = _normalize_path_list(payload.debloat_add_system)
    debloat_add_product = _normalize_path_list(payload.debloat_add_product)
    debloat_disabled_json = json.dumps(sorted(set(debloat_disabled)), ensure_ascii=True)
    debloat_add_system_json = json.dumps(debloat_add_system, ensure_ascii=True)
    debloat_add_product_json = json.dumps(debloat_add_product, ensure_ascii=True)
    debloat_signature = hashlib.new("sha512_256", debloat_disabled_json.encode("utf-8")).hexdigest()[:16]
    debloat_add_system_signature = hashlib.new("sha512_256", debloat_add_system_json.encode("utf-8")).hexdigest()[:16]
    debloat_add_product_signature = hashlib.new("sha512_256", debloat_add_product_json.encode("utf-8")).hexdigest()[:16]

    ff_overrides_json = None
    ff_signature = ""
    if payload.ff_overrides:
        ff_data = _collect_ff_defaults(ws, payload.target, source_firmware, target_firmware)
        valid_ff_keys = {entry["key"] for entry in ff_data.get("entries", []) if entry.get("key")}
        invalid_keys = [k for k in payload.ff_overrides if k not in valid_ff_keys]
        if invalid_keys:
            raise HTTPException(400, f"Unknown floating feature keys: {', '.join(invalid_keys[:5])}")
        normalized = {k: normalize_ff_value(v) for k, v in payload.ff_overrides.items()}
        ff_overrides_json = json.dumps(normalized, ensure_ascii=True, sort_keys=True)
        ff_signature = hashlib.new("sha512_256", ff_overrides_json.encode("utf-8")).hexdigest()[:16]

    # The upload is only consumed once every other input has validated, so a
    # rejected request does not burn the archive the user just uploaded
    extra_mods_signature = ""
    extra_mods_archive_path = None
    extra_mods_modules_json = None
    upload_meta = None
    if payload.extra_mods_upload_id:
        upload_meta = load_upload_meta(settings.data_dir, payload.extra_mods_upload_id)
        if not upload_meta:
            raise HTTPException(400, "Invalid extra_mods_upload_id")
        if upload_meta.get("used"):
            raise HTTPException(400, "This uploaded mods archive has already been used")
        archive_path = upload_meta.get("archive_path")
        if not archive_path or not Path(archive_path).exists():
            raise HTTPException(400, "Uploaded mods archive file is missing")
        extra_mods_archive_path = archive_path
        modules = upload_meta.get("modules", [])
        extra_mods_modules_json = json.dumps(modules, ensure_ascii=True)
        extra_mods_signature = hashlib.new("sha512_256", extra_mods_modules_json.encode("utf-8")).hexdigest()[:16]

    build_signature = _build_signature(
        ws.id,
        payload.target,
        source_commit,
        source_firmware,
        target_firmware,
        version_major,
        version_minor,
        version_patch,
        version_suffix,
        extra_mods_signature,
        debloat_signature,
        debloat_add_system_signature,
        debloat_add_product_signature,
        mods_signature,
        ff_signature,
    )

    # Reuse an already built artifact for the same build signature unless forced
    if not payload.force and not payload.no_rom_zip:
        existing = (
            db.query(BuildJob)
            .filter(
                BuildJob.build_signature == build_signature,
                BuildJob.status.in_(("succeeded", "reused")),
                BuildJob.artifact_path.isnot(None),
            )
            .order_by(desc(BuildJob.finished_at), desc(BuildJob.created_at))
            .first()
        )
        if existing and existing.artifact_path and Path(existing.artifact_path).exists():
            now = datetime.now(UTC)
            if extra_mods_archive_path:
                try:
                    Path(extra_mods_archive_path).unlink(missing_ok=True)
                except Exception:
                    pass
            if upload_meta is not None and payload.extra_mods_upload_id:
                upload_meta["used"] = True
                save_upload_meta(settings.data_dir, payload.extra_mods_upload_id, upload_meta)
            job = BuildJob(
                workspace_id=ws.id,
                target=payload.target,
                source_commit=source_commit,
                source_firmware=source_firmware,
                target_firmware=target_firmware,
                version_major=version_major,
                version_minor=version_minor,
                version_patch=version_patch,
                version_suffix=version_suffix,
                build_signature=build_signature,
                force=payload.force,
                no_rom_zip=payload.no_rom_zip,
                skip_target_files=payload.skip_target_files,
                status="reused",
                return_code=0,
                artifact_path=existing.artifact_path,
                reused_from_job_id=existing.id,
                extra_mods_archive_path=None,
                extra_mods_modules_json=extra_mods_modules_json,
                debloat_disabled_json=debloat_disabled_json,
                debloat_add_system_json=debloat_add_system_json,
                debloat_add_product_json=debloat_add_product_json,
                mods_disabled_json=mods_disabled_json,
                ff_overrides_json=ff_overrides_json,
                started_at=now,
                finished_at=now,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            publish_job_event(job)
            return job

    # An incremental zip is packed right after the build, so the base has to be a
    # finished build of the same target whose target-files archive is still there
    incremental_base_job_id = None
    if payload.incremental_base_job_id:
        if payload.skip_target_files:
            raise HTTPException(400, "An incremental zip needs the target-files archive")
        base = db.get(BuildJob, payload.incremental_base_job_id)
        if not base or base.workspace_id != ws.id:
            raise HTTPException(404, "Base build not found")
        if base.target != payload.target:
            raise HTTPException(400, "Both builds must be for the same target")
        if not base.target_files_path or not Path(str(base.target_files_path)).is_file():
            raise HTTPException(400, "Target-files zip is not available for this build")
        incremental_base_job_id = base.id

    if upload_meta is not None and payload.extra_mods_upload_id:
        upload_meta["used"] = True
        save_upload_meta(settings.data_dir, payload.extra_mods_upload_id, upload_meta)

    job = BuildJob(
        workspace_id=ws.id,
        target=payload.target,
        source_commit=source_commit,
        source_firmware=source_firmware,
        target_firmware=target_firmware,
        version_major=version_major,
        version_minor=version_minor,
        version_patch=version_patch,
        version_suffix=version_suffix,
        build_signature=build_signature,
        force=payload.force,
        no_rom_zip=payload.no_rom_zip,
        skip_target_files=payload.skip_target_files,
        incremental_base_job_id=incremental_base_job_id,
        extra_mods_archive_path=extra_mods_archive_path,
        extra_mods_modules_json=extra_mods_modules_json,
        debloat_disabled_json=debloat_disabled_json,
        debloat_add_system_json=debloat_add_system_json,
        debloat_add_product_json=debloat_add_product_json,
        mods_disabled_json=mods_disabled_json,
        ff_overrides_json=ff_overrides_json,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job.queue_job_id = await _enqueue_build("build_job_task", job.id)
    db.commit()
    db.refresh(job)
    publish_job_event(job)
    return job


@app.get(f"{settings.api_prefix}/build/targets")
async def build_targets(workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    target_options = await asyncio.to_thread(_get_target_options, ws)
    targets = [str(x.get("code") or "") for x in target_options if x.get("code")]
    if not target_options:
        targets = await asyncio.to_thread(_get_targets, ws)
        target_options = [{"code": code, "name": code} for code in targets]
    selected = "b0s" if "b0s" in targets else (targets[0] if targets else "")
    root = _project_root(ws)
    return {
        "workspace_id": ws.id,
        "fw_scope": ws.fw_scope,
        "targets": targets,
        "target_options": target_options,
        "target": selected,
        "repo_root": str(root) if root else "",
    }


@app.get(f"{settings.api_prefix}/build/defaults")
async def build_defaults(target: str | None = None, workspace: str | None = None, db: Session = Depends(get_db)):
    # Only the form values, so the build card does not wait on the firmware
    # lookups that need the network
    ws = _require_ws(db, workspace)
    targets = await asyncio.to_thread(_get_targets, ws)
    selected = target if target in targets else ("b0s" if "b0s" in targets else (targets[0] if targets else ""))
    defaults = await asyncio.to_thread(_get_defaults_for_target, ws, selected) if selected else {}
    return {
        "target": selected,
        "defaults": defaults,
        "capabilities": await asyncio.to_thread(_repo_capabilities, ws),
        "latest_artifact_available": await asyncio.to_thread(
            _target_has_latest_artifact_with_new_session, ws.id, selected
        ),
    }


@app.get(f"{settings.api_prefix}/firmware/status")
async def firmware_status_endpoint(
    target: str | None = None, workspace: str | None = None, db: Session = Depends(get_db)
):
    ws = _require_ws(db, workspace)
    targets = await asyncio.to_thread(_get_targets, ws)
    selected = target if target in targets else ("b0s" if "b0s" in targets else (targets[0] if targets else ""))
    defaults = await asyncio.to_thread(_get_defaults_for_target, ws, selected) if selected else {}
    fw_info = await asyncio.to_thread(_collect_samsung_fw, ws)
    await asyncio.to_thread(_fill_latest_for_fw_items, fw_info["items"])
    source_status, target_status = await asyncio.gather(
        asyncio.to_thread(_make_firmware_status, str(defaults.get("source_firmware", "")), fw_info["items"]),
        asyncio.to_thread(_make_firmware_status, str(defaults.get("target_firmware", "")), fw_info["items"]),
    )
    return {
        "fw_scope": ws.fw_scope,
        "firmware_status": source_status,
        "target_firmware_status": target_status,
    }


@app.get(f"{settings.api_prefix}/repo/info")
async def repo_info(workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    return await asyncio.to_thread(_repo_info, ws)


@app.patch(f"{settings.api_prefix}/repo/config")
async def update_repo_config(payload: RepoConfigUpdate, workspace: str | None = None, db: Session = Depends(get_db)):
    value = (payload.git_url or "").strip()
    if not re.match(r"^(https://|git@|ssh://).+", value):
        raise HTTPException(400, "Invalid git url")
    ws_row = ws_lib.get_workspace(db, workspace)
    if ws_row is None:
        raise HTTPException(400, "No workspace configured")
    ws_row.git_url = value
    if payload.git_ref is not None and payload.git_ref.strip():
        ws_row.git_ref = payload.git_ref.strip()
    if payload.git_username is not None:
        ws_row.git_username = payload.git_username.strip()
    if payload.git_token is not None:
        ws_row.git_token = payload.git_token.strip()
    db.commit()
    db.refresh(ws_row)
    _invalidate_repo_caches(ws_row.id)
    return await asyncio.to_thread(_repo_info, ws_lib.snapshot(ws_row))


@app.get(f"{settings.api_prefix}/settings/retention")
async def get_retention(db: Session = Depends(get_db)):
    return {
        "rom_zips": int(_get_setting(db, RETENTION_ROM_KEY, "0") or 0),
        "target_files": int(_get_setting(db, RETENTION_TARGET_FILES_KEY, "0") or 0),
    }


@app.patch(f"{settings.api_prefix}/settings/retention")
async def update_retention(payload: RetentionUpdate, db: Session = Depends(get_db)):
    if payload.rom_zips is not None:
        _set_setting(db, RETENTION_ROM_KEY, str(payload.rom_zips))
    if payload.target_files is not None:
        _set_setting(db, RETENTION_TARGET_FILES_KEY, str(payload.target_files))
    keep_rom = int(_get_setting(db, RETENTION_ROM_KEY, "0") or 0)
    keep_tf = int(_get_setting(db, RETENTION_TARGET_FILES_KEY, "0") or 0)
    removed = await asyncio.to_thread(apply_artifact_retention, keep_rom, keep_tf)
    return {"rom_zips": keep_rom, "target_files": keep_tf, "removed": removed}


@app.get(f"{settings.api_prefix}/settings/advanced")
async def get_advanced_settings(target: str | None = None, workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    return await asyncio.to_thread(_advanced_settings_payload, ws, target)


def _advanced_settings_payload(ws: WorkspaceRef, target: str | None) -> dict:
    root = _project_root(ws) or Path(ws.root)
    candidates = _list_config_candidates(root)
    preferred = _preferred_source_configs_for_target(root, target or "")
    auto_value, auto_source = _read_source_firmware_from_configs_with_source(root, None, preferred)
    return {
        "source_config_candidates": candidates,
        "source_config_override": ws.source_config_override,
        "source_config_auto": auto_source,
        "source_firmware_auto": auto_value,
        "source_config_preferred": preferred,
        "targets_override": ws.targets_override,
        "targets_detected": _get_targets_detected(ws),
        "targets_effective": _get_targets(ws),
    }


@app.patch(f"{settings.api_prefix}/settings/advanced")
async def update_advanced_settings(
    payload: AdvancedSettingsUpdate,
    target: str | None = None,
    workspace: str | None = None,
    db: Session = Depends(get_db),
):
    ws_row = ws_lib.get_workspace(db, workspace)
    if ws_row is None:
        raise HTTPException(400, "No workspace configured")
    ws = ws_lib.snapshot(ws_row)
    root = _project_root(ws) or Path(ws.root)
    candidate_names = {str(x.get("name") or "") for x in _list_config_candidates(root)}

    if payload.source_config_override is not None:
        value = (payload.source_config_override or "").strip()
        if value.lower() in ("", "auto", "none"):
            ws_row.source_config_override = ""
        else:
            if value not in candidate_names:
                raise HTTPException(400, "Unknown source config override")
            ws_row.source_config_override = value

    if payload.targets_override is not None:
        ws_row.targets_override = (payload.targets_override or "").strip()

    db.commit()
    db.refresh(ws_row)
    return await asyncio.to_thread(_advanced_settings_payload, ws_lib.snapshot(ws_row), target)


@app.post(f"{settings.api_prefix}/repo/clone", response_model=BuildJobRead)
async def repo_clone(fresh: bool = False, workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    if not ws.git_url:
        raise HTTPException(400, "Workspace has no git url configured")
    label = "Repo re-clone" if fresh else "Repo clone"
    op_job = _create_operation_job(
        db,
        workspace_id=ws.id,
        target="repo",
        operation_name=f"{label}: {_safe_git_url(ws.git_url)}",
    )
    _invalidate_repo_caches(ws.id)
    op_job.queue_job_id = await _enqueue_build("repo_clone_job_task", op_job.id, bool(fresh))
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/repo/pull", response_model=BuildJobRead)
async def repo_pull(workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    op_job = _create_operation_job(db, workspace_id=ws.id, target="repo", operation_name=f"Repo pull: {ws.git_ref}")
    _invalidate_repo_caches(ws.id)
    op_job.queue_job_id = await _enqueue_build("repo_pull_job_task", op_job.id)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/repo/submodules", response_model=BuildJobRead)
async def repo_submodules(workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    op_job = _create_operation_job(db, workspace_id=ws.id, target="repo", operation_name="Repo submodules update")
    _invalidate_repo_caches(ws.id)
    op_job.queue_job_id = await _enqueue_build("repo_submodules_job_task", op_job.id)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.delete(f"{settings.api_prefix}/repo", response_model=BuildJobRead)
async def repo_delete(mode: str = "repo_only", workspace: str | None = None, db: Session = Depends(get_db)):
    if mode not in {"repo_only", "repo_with_out"}:
        raise HTTPException(400, "mode must be repo_only or repo_with_out")
    ws = _require_ws(db, workspace)
    op_name = "Repo delete (keep out)" if mode == "repo_only" else "Repo delete (with out)"
    op_job = _create_operation_job(db, workspace_id=ws.id, target="repo", operation_name=op_name)
    _invalidate_repo_caches(ws.id)
    op_job.queue_job_id = await _enqueue_build("repo_delete_job_task", op_job.id, mode)
    db.commit()
    db.refresh(op_job)
    return op_job


# Ceiling on one drain pass, so a runaway publisher cannot hold the event loop
_PUBSUB_DRAIN_LIMIT = 500
# A connection dropped by something in the middle leaves the browser holding an
# open socket that never fires close, so every stream has to keep talking
_WS_PING_INTERVAL_SEC = 20.0

# Log tailing polls the file: fast while it grows, lazy once it goes quiet
_LOG_POLL_MIN_SEC = 0.15
_LOG_POLL_MAX_SEC = 0.4
_LOG_POLL_STEP_SEC = 0.05
_LOG_STATUS_INTERVAL_SEC = 1.0


async def _pump_pubsub(websocket: WebSocket, channel: str, snapshot: dict, error_label: str):
    # One shared loop for all three progress streams: send a snapshot, then relay
    # everything published on the channel until the client goes away
    pubsub = redis_conn.pubsub(ignore_subscribe_messages=True)

    def decode(message):
        data = message.get("data")
        try:
            return json.loads(data.decode("utf-8") if isinstance(data, bytes) else str(data))
        except Exception:
            return {"type": "error", "message": error_label}

    try:
        await websocket.send_json(snapshot)
        await asyncio.to_thread(pubsub.subscribe, channel)
        last_sent = time.time()
        while True:
            # Block for the first message, then take everything already queued
            # behind it. Publishers burst faster than one message per tick, and
            # a client that drains slower than that trails a finished build
            message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
            drained = 0
            while message and drained < _PUBSUB_DRAIN_LIMIT:
                if message.get("type") == "message":
                    await websocket.send_json(decode(message))
                    last_sent = time.time()
                drained += 1
                message = await asyncio.to_thread(pubsub.get_message, timeout=0.0)
            if time.time() - last_sent >= _WS_PING_INTERVAL_SEC:
                await websocket.send_json({"type": "ping"})
                last_sent = time.time()
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        # Socket closed while a send was in flight
        pass
    finally:
        try:
            await asyncio.to_thread(pubsub.close)
        except Exception:
            pass


@app.websocket(f"{settings.api_prefix}/repo/progress/ws")
async def stream_repo_progress_ws(websocket: WebSocket):
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    items = await asyncio.to_thread(list_repo_progress)
    await _pump_pubsub(
        websocket,
        REPO_PROGRESS_CHANNEL,
        {"type": "snapshot", "items": list(items.values())},
        "bad repo progress payload",
    )


@app.get(f"{settings.api_prefix}/debloat/options")
async def get_debloat_options(workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    root = _project_root(ws) or Path(ws.root)
    entries = await asyncio.to_thread(parse_unica_debloat_entries, root)
    return {"entries": entries}


@app.get(f"{settings.api_prefix}/floating/features")
async def get_floating_features(target: str, workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    if target not in _get_targets(ws):
        raise HTTPException(400, "Unknown target")
    defaults = await asyncio.to_thread(_get_defaults_for_target, ws, target)
    source_firmware = str(defaults.get("source_firmware", ""))
    target_firmware = str(defaults.get("target_firmware", ""))
    return await asyncio.to_thread(_collect_ff_defaults, ws, target, source_firmware, target_firmware)


@app.get(f"{settings.api_prefix}/mods/options")
async def get_mods_options(workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    root = _project_root(ws) or Path(ws.root)
    entries = await asyncio.to_thread(parse_unica_mod_entries, root)
    return {"entries": entries}


@app.get(f"{settings.api_prefix}/firmware/samsung")
async def get_samsung_fw(workspace: str | None = None, db: Session = Depends(get_db)):
    # Firmware screen data: cache contents, sizes, latest version, update_available
    ws = _require_ws(db, workspace)
    items = (await asyncio.to_thread(_collect_samsung_fw, ws))["items"]
    await asyncio.to_thread(_fill_latest_for_fw_items, items)
    progress = await asyncio.to_thread(list_progress)
    for item in items:
        latest = str(item.get("latest_version") or "")
        item["latest_version"] = latest
        downloaded = str(item.get("odin_version") or "")
        extracted = str(item.get("fw_version") or "")
        item["update_available"] = bool(latest and downloaded and downloaded != latest and extracted != latest)
        item["progress"] = progress.get(progress_key(ws.fw_scope, str(item.get("key") or "")))
    return {"items": items, "fw_scope": ws.fw_scope, "shared_fw_cache": ws.shared_fw_cache}


@app.websocket(f"{settings.api_prefix}/firmware/progress/ws")
async def stream_firmware_progress_ws(websocket: WebSocket):
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    progress = await asyncio.to_thread(list_progress)
    await _pump_pubsub(
        websocket,
        PROGRESS_CHANNEL,
        {"type": "snapshot", "items": list(progress.values())},
        "bad firmware progress payload",
    )


# The sections the state stream can deliver. Each one is computed and sent on
# its own, so a slow firmware lookup never delays the build form
STATE_SECTIONS = ("targets", "defaults", "firmware", "repo", "jobs")


def _state_section(section: str, workspace_id: str | None, target: str | None) -> dict:
    db = SessionLocal()
    try:
        ws = _require_ws(db, workspace_id)
    finally:
        db.close()

    if section == "targets":
        target_options = _get_target_options(ws)
        targets = [str(x.get("code") or "") for x in target_options if x.get("code")]
        if not target_options:
            targets = _get_targets(ws)
            target_options = [{"code": code, "name": code} for code in targets]
        root = _project_root(ws)
        return {
            "workspace_id": ws.id,
            "fw_scope": ws.fw_scope,
            "targets": targets,
            "target_options": target_options,
            "target": "b0s" if "b0s" in targets else (targets[0] if targets else ""),
            "repo_root": str(root) if root else "",
        }

    targets = _get_targets(ws)
    selected = target if target in targets else ("b0s" if "b0s" in targets else (targets[0] if targets else ""))

    if section == "defaults":
        defaults = _get_defaults_for_target(ws, selected) if selected else {}
        return {
            "target": selected,
            "defaults": defaults,
            "capabilities": _repo_capabilities(ws),
            "latest_artifact_available": _target_has_latest_artifact_with_new_session(ws.id, selected),
        }

    if section == "firmware":
        defaults = _get_defaults_for_target(ws, selected) if selected else {}
        fw_info = _collect_samsung_fw(ws)
        _fill_latest_for_fw_items(fw_info["items"])
        return {
            "fw_scope": ws.fw_scope,
            "firmware_status": _make_firmware_status(str(defaults.get("source_firmware", "")), fw_info["items"]),
            "target_firmware_status": _make_firmware_status(str(defaults.get("target_firmware", "")), fw_info["items"]),
        }

    if section == "repo":
        return _repo_info(ws)

    if section == "jobs":
        jobs = _list_jobs_with_new_session(ws.id, 50)
        return {"items": [BuildJobRead.model_validate(job).model_dump(mode="json") for job in jobs]}

    raise HTTPException(400, f"Unknown section: {section}")


@app.websocket(f"{settings.api_prefix}/state/ws")
async def stream_state_ws(websocket: WebSocket):
    # The default transport for everything the UI shows: sections are pushed on
    # connect and again whenever a job moves. The REST endpoints stay as the
    # fallback for when a websocket cannot be established at all
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return

    ctx = {
        "workspace": websocket.query_params.get("workspace") or None,
        "target": websocket.query_params.get("target") or None,
    }
    send_lock = asyncio.Lock()

    async def send(payload: dict):
        async with send_lock:
            await websocket.send_json(payload)

    async def send_section(section: str):
        try:
            data = await asyncio.to_thread(_state_section, section, ctx["workspace"], ctx["target"])
        except HTTPException as exc:
            await send({"type": "section_error", "section": section, "message": str(exc.detail)})
            return
        except Exception as exc:
            await send({"type": "section_error", "section": section, "message": str(exc)})
            return
        await send({"type": "section", "section": section, "data": data})

    async def send_sections(sections):
        await asyncio.gather(*[send_section(name) for name in sections])

    async def pubsub_loop():
        pubsub = redis_conn.pubsub(ignore_subscribe_messages=True)
        try:
            await asyncio.to_thread(pubsub.subscribe, JOB_EVENTS_CHANNEL)
            while True:
                message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if message and message.get("type") == "message":
                    raw = message.get("data")
                    try:
                        event = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
                    except Exception:
                        continue
                    if ctx["workspace"] and event.get("workspace_id") not in ("", None, ctx["workspace"]):
                        continue
                    await send({"type": "job", "job": event})
                    sections = ["jobs"]
                    if event.get("job_kind") == "operation" and event.get("status") in _TERMINAL_JOB_STATES:
                        sections += ["repo", "firmware", "targets", "defaults"]
                    await send_sections(sections)
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await asyncio.to_thread(pubsub.close)
            except Exception:
                pass

    async def client_loop():
        while True:
            payload = await websocket.receive_json()
            action = str(payload.get("action") or "")
            if action == "subscribe":
                if "workspace" in payload:
                    ctx["workspace"] = payload.get("workspace") or None
                if "target" in payload:
                    ctx["target"] = payload.get("target") or None
                requested = payload.get("sections") or list(STATE_SECTIONS)
                await send_sections([x for x in requested if x in STATE_SECTIONS])
            elif action == "refresh":
                requested = payload.get("sections") or list(STATE_SECTIONS)
                await send_sections([x for x in requested if x in STATE_SECTIONS])

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(_WS_PING_INTERVAL_SEC)
            await send({"type": "ping"})

    await send({"type": "ready"})
    await send_sections(STATE_SECTIONS)

    tasks = [
        asyncio.create_task(pubsub_loop()),
        asyncio.create_task(client_loop()),
        asyncio.create_task(heartbeat_loop()),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@app.websocket(f"{settings.api_prefix}/jobs/events/ws")
async def stream_job_events_ws(websocket: WebSocket):
    # Replaces polling the jobs list: every status change is announced here, and
    # the client only refetches when something actually moved
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    await _pump_pubsub(websocket, JOB_EVENTS_CHANNEL, {"type": "ready"}, "bad job event payload")


@app.websocket(f"{settings.api_prefix}/build/progress/ws")
async def stream_build_progress_ws(websocket: WebSocket):
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    progress = await asyncio.to_thread(list_build_progress)
    await _pump_pubsub(
        websocket,
        BUILD_PROGRESS_CHANNEL,
        {"type": "snapshot", "items": list(progress.values())},
        "bad build progress payload",
    )


@app.delete(f"{settings.api_prefix}/firmware/samsung/{{fw_type}}/{{fw_key}}", response_model=BuildJobRead)
async def delete_samsung_fw_entry(
    fw_type: str,
    fw_key: str,
    target: str | None = None,
    workspace: str | None = None,
    db: Session = Depends(get_db),
):
    # Deletion runs as a queued operation job so it is logged and cancellable
    if fw_type not in {"odin", "fw"}:
        raise HTTPException(400, "fw_type must be 'odin' or 'fw'")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", fw_key):
        raise HTTPException(400, "Invalid fw key")

    ws = _require_ws(db, workspace)
    targets = _get_targets(ws)
    selected_target = target or ("b0s" if "b0s" in targets else (targets[0] if targets else ""))
    if not selected_target:
        raise HTTPException(400, "No targets available")
    if selected_target not in targets:
        raise HTTPException(400, "Unknown target")

    base = Path(ws.out) / ("odin" if fw_type == "odin" else "fw")
    fw_path = base / fw_key
    if not fw_path.exists():
        raise HTTPException(404, "FW entry not found")
    if not fw_path.is_dir():
        raise HTTPException(400, "FW entry is not a directory")

    op_job = _create_operation_job(
        db,
        workspace_id=ws.id,
        target=selected_target,
        operation_name=f"Delete {fw_type.upper()} FW entry: {fw_key}",
    )
    op_job.queue_job_id = await _enqueue_build("delete_fw_job_task", op_job.id, fw_type, fw_key)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.get(f"{settings.api_prefix}/artifacts/target/files")
async def list_target_files(target: str, workspace: str | None = None, db: Session = Depends(get_db)):
    # Only builds of the same target can be compared, and only while the archive
    # they produced is still on disk
    ws = _require_ws(db, workspace)
    rows = (
        db.query(BuildJob)
        .filter(
            BuildJob.workspace_id == ws.id,
            BuildJob.job_kind == "build",
            BuildJob.status == "succeeded",
            BuildJob.target == target,
            BuildJob.target_files_path.isnot(None),
        )
        .order_by(BuildJob.finished_at.desc())
        .limit(50)
        .all()
    )
    items = []
    for row in rows:
        path = Path(str(row.target_files_path or ""))
        if not path.is_file():
            continue
        items.append(
            {
                "job_id": row.id,
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "finished_at": row.finished_at.isoformat() if row.finished_at else "",
            }
        )
    return {"items": items}


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/incremental", response_model=BuildJobRead)
async def queue_incremental_zip(
    job_id: str,
    base_job_id: str,
    workspace: str | None = None,
    db: Session = Depends(get_db),
):
    ws = _require_ws(db, workspace)
    job = db.get(BuildJob, job_id)
    base = db.get(BuildJob, base_job_id)
    if not job or not base:
        raise HTTPException(404, "Job not found")
    if job.target != base.target:
        raise HTTPException(400, "Both builds must be for the same target")
    if job.id == base.id:
        raise HTTPException(400, "Pick a different build as the base")
    for row in (job, base):
        if not row.target_files_path or not Path(str(row.target_files_path)).is_file():
            raise HTTPException(400, "Target-files zip is not available for this build")

    op_job = _create_operation_job(
        db,
        workspace_id=ws.id,
        target=job.target,
        operation_name=f"Incremental zip: {job.target} from {Path(str(base.target_files_path)).name}",
    )
    op_job.queue_job_id = await _enqueue_build(
        "incremental_zip_job_task",
        op_job.id,
        str(base.target_files_path),
        str(job.target_files_path),
        job.target,
    )
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/delta", response_model=BuildJobRead)
async def queue_delta_patch(
    job_id: str,
    base_job_id: str,
    kind: str = "rom",
    workspace: str | None = None,
    db: Session = Depends(get_db),
):
    # Both sides have to be artifacts of the same kind, or the patch would be
    # measured against something the user does not hold
    column = {"rom": "artifact_path", "target_files": "target_files_path"}.get(kind)
    if not column:
        raise HTTPException(400, "kind must be rom or target_files")

    ws = _require_ws(db, workspace)
    job = db.get(BuildJob, job_id)
    base = db.get(BuildJob, base_job_id)
    if not job or not base or job.workspace_id != ws.id:
        raise HTTPException(404, "Job not found")
    if job.id == base.id:
        raise HTTPException(400, "Pick a different build as the base")

    paths = []
    for row in (base, job):
        value = getattr(row, column, None)
        if not value or not Path(str(value)).is_file():
            raise HTTPException(400, "Artifact is not available for this build")
        paths.append(str(value))

    op_job = _create_operation_job(
        db,
        workspace_id=ws.id,
        target=job.target,
        operation_name=f"Delta: {Path(paths[1]).name} from {Path(paths[0]).name}",
    )
    op_job.queue_job_id = await _enqueue_build("delta_patch_job_task", op_job.id, paths[0], paths[1])
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/dsu", response_model=BuildJobRead)
async def queue_dsu_package(job_id: str, workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    job = db.get(BuildJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.target_files_path or not Path(str(job.target_files_path)).is_file():
        raise HTTPException(400, "Target-files zip is not available for this build")

    op_job = _create_operation_job(
        db,
        workspace_id=ws.id,
        target=job.target,
        operation_name=f"DSU package: {job.target} from {Path(str(job.target_files_path)).name}",
    )
    op_job.queue_job_id = await _enqueue_build(
        "dsu_package_job_task",
        op_job.id,
        str(job.target_files_path),
        job.target,
    )
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/firmware/download", response_model=BuildJobRead)
async def download_samsung_fw(
    target: str | None = None,
    kind: str = "both",
    workspace: str | None = None,
    db: Session = Depends(get_db),
):
    # Downloading ahead of a build: the firmware is the slow part of a first run
    if kind not in ("source", "target", "both"):
        raise HTTPException(400, "kind must be source, target or both")

    ws = _require_ws(db, workspace)
    targets = _get_targets(ws)
    selected_target = target or ("b0s" if "b0s" in targets else (targets[0] if targets else ""))
    if not selected_target:
        raise HTTPException(400, "No targets available")
    if selected_target not in targets:
        raise HTTPException(400, "Unknown target")

    labels = {"source": "source FW", "target": "target FW", "both": "source and target FW"}
    op_job = _create_operation_job(
        db,
        workspace_id=ws.id,
        target=selected_target,
        operation_name=f"Download {labels[kind]}: {selected_target}",
    )
    # Progress is filed under MODEL_CSC, so the keys travel with the job and the
    # bar lands on the right card
    defaults = _get_defaults_for_target(ws, selected_target)
    fw_keys = []
    for field, wanted in (("source_firmware", "source"), ("target_firmware", "target")):
        if kind in (wanted, "both"):
            model, csc = _parse_model_csc(str(defaults.get(field) or ""))
            if model and csc:
                fw_keys.append(f"{model}_{csc}".upper())

    op_job.queue_job_id = await _enqueue_build("download_fw_job_task", op_job.id, selected_target, kind, fw_keys)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/firmware/samsung/{{fw_key}}/extract", response_model=BuildJobRead)
async def extract_samsung_fw(
    fw_key: str,
    target: str | None = None,
    workspace: str | None = None,
    db: Session = Depends(get_db),
):
    # Extract is queued too: heavy I/O and a long runtime need logs and a status
    if not re.fullmatch(r"[A-Za-z0-9._-]+", fw_key):
        raise HTTPException(400, "Invalid fw key")

    ws = _require_ws(db, workspace)
    targets = _get_targets(ws)
    selected_target = target or ("b0s" if "b0s" in targets else (targets[0] if targets else ""))
    if not selected_target:
        raise HTTPException(400, "No targets available")
    if selected_target not in targets:
        raise HTTPException(400, "Unknown target")

    odin_dir = Path(ws.out) / "odin" / fw_key
    if not odin_dir.is_dir():
        raise HTTPException(404, "ODIN FW entry not found")

    op_job = _create_operation_job(
        db,
        workspace_id=ws.id,
        target=selected_target,
        operation_name=f"Extract FW (-f): {fw_key}",
    )
    op_job.queue_job_id = await _enqueue_build("extract_fw_job_task", op_job.id, fw_key, selected_target)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/mods/upload")
async def upload_mods_archive(file: UploadFile = File(...)):
    upload_id = new_upload_id()
    archive_path = upload_archive_path(settings.data_dir, upload_id, file.filename or "mods.bin")
    work_dir = Path(settings.data_dir) / "uploads" / upload_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        with archive_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

        validated = validate_mods_archive(archive_path, work_dir)
        modules = validated["modules"]

        save_upload_meta(
            settings.data_dir,
            upload_id,
            {
                "used": False,
                "archive_path": str(archive_path),
                "modules": modules,
            },
        )
        return {"upload_id": upload_id, "modules": modules}
    except ModsArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/jobs", response_model=list[BuildJobRead])
async def list_jobs(limit: int = 50, workspace: str | None = None, db: Session = Depends(get_db)):
    ws = _require_ws(db, workspace)
    return await asyncio.to_thread(_list_jobs_with_new_session, ws.id, limit)


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", response_model=BuildJobRead)
async def get_job(job_id: str):
    job = await asyncio.to_thread(_get_job_with_new_session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/artifact")
async def download_artifact(job_id: str):
    p = await asyncio.to_thread(_get_job_artifact_path_with_new_session, job_id)
    return FileResponse(path=p, filename=p.name, media_type="application/zip")


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/artifact/blockmap")
async def artifact_block_map(job_id: str):
    # Hashing a multi gigabyte file is slow enough to keep next to the artifact
    p = await asyncio.to_thread(_get_job_artifact_path_with_new_session, job_id)
    return await asyncio.to_thread(cached_block_map, p)


@app.delete(f"{settings.api_prefix}/jobs/{{job_id}}/artifact")
async def delete_artifact(job_id: str, kind: str = "rom", db: Session = Depends(get_db)):
    # Both archives are large enough that keeping them around is a choice, so
    # each can go without touching the job record itself
    if kind not in ("rom", "target_files", "both"):
        raise HTTPException(400, "kind must be rom, target_files or both")
    job = db.get(BuildJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    columns = {"rom": ("artifact_path",), "target_files": ("target_files_path",)}
    columns["both"] = columns["rom"] + columns["target_files"]

    removed = []
    for name in columns[kind]:
        value = getattr(job, name, None)
        if not value:
            continue
        path = Path(str(value))
        if path.is_file():
            await asyncio.to_thread(path.unlink)
            removed.append(path.name)
        setattr(job, name, None)

    db.commit()
    db.refresh(job)
    publish_job_event(job)
    return {"removed": removed}


@app.get(f"{settings.api_prefix}/artifacts/latest/{{target}}")
async def download_latest_artifact_for_target(target: str, workspace: str | None = None, db: Session = Depends(get_db)):
    # Latest successful/reused artifact for the target, behind the Latest ZIP button
    ws = _require_ws(db, workspace)
    if target not in _get_targets(ws):
        raise HTTPException(400, "Unknown target")
    p = await asyncio.to_thread(_get_latest_artifact_path_for_target, ws.id, target)
    return FileResponse(path=p, filename=p.name, media_type="application/zip")


@app.get(f"{settings.api_prefix}/artifacts/history")
async def artifacts_history(
    target: str | None = None,
    limit: int = 50,
    workspace: str | None = None,
    db: Session = Depends(get_db),
):
    ws = _require_ws(db, workspace)
    items = await asyncio.to_thread(_list_artifacts_with_new_session, ws.id, target, limit)
    return {"items": items}


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/stop", response_model=BuildJobRead)
async def stop_job(job_id: str, payload: StopJobRequest | None = None, db: Session = Depends(get_db)):
    # Stopping a running job goes to the control queue: only the worker shares its PID namespace
    job = db.get(BuildJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status in {"succeeded", "failed", "reused", "canceled"}:
        return job

    signal_type = payload.signal_type if payload else "sigterm"

    if job.status == "queued":
        job.status = "canceled"
        job.error = "Build canceled by user (queued job)"
        job.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(job)
        publish_job_event(job)
        return job

    # Running jobs are stopped from worker-side control queue to avoid PID namespace issues in API container.
    # The worker owns job.error from here on: writing an outcome now would report
    # a stop that has not happened yet
    await _enqueue_control("stop_job_task", job.id, signal_type)
    return job


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/hints")
async def job_hints(job_id: str):
    job = await asyncio.to_thread(_get_job_with_new_session, job_id)
    if not job or not job.log_path:
        raise HTTPException(404, "Log file not found")
    log_path = Path(job.log_path)
    log_text = await asyncio.to_thread(_read_log_tail_text, log_path, 512)
    hints = detect_build_hints(log_text)
    return {"hints": hints}


def _get_job_log_snapshot(job_id: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return {"exists": "0", "status": "", "log_path": ""}
        return {
            "exists": "1",
            "status": str(job.status or ""),
            "log_path": str(job.log_path or ""),
        }
    finally:
        db.close()


def _read_log_chunk(path: Path, pos: int) -> tuple[str, int]:
    if not path.exists():
        return "", pos
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        f.seek(pos)
        chunk = f.read()
        return chunk, f.tell()


def _tail_log_start_pos(path: Path, tail_kb: int) -> int:
    if not path.exists() or tail_kb <= 0:
        return 0
    size = path.stat().st_size
    pos = max(0, size - (tail_kb * 1024))
    if pos <= 0:
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        f.seek(pos)
        _ = f.readline()
        return f.tell()


def _read_log_tail_text(path: Path, tail_kb: int = 256) -> str:
    if not path.exists():
        return ""
    pos = _tail_log_start_pos(path, tail_kb)
    chunk, _ = _read_log_chunk(path, pos)
    return chunk


_TERMINAL_JOB_STATES = {"succeeded", "failed", "canceled", "reused"}


@app.websocket(f"{settings.api_prefix}/jobs/{{job_id}}/ws")
async def stream_logs_ws(websocket: WebSocket, job_id: str, tail_kb: int = 256):
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    try:
        snap = await asyncio.to_thread(_get_job_log_snapshot, job_id)
        if snap.get("exists") != "1":
            await websocket.send_json({"type": "error", "message": "Job not found"})
            await websocket.close(code=1008)
            return

        if not snap.get("log_path"):
            await websocket.send_json({"type": "error", "message": "Log file not available yet"})
            await websocket.close(code=1008)
            return

        log_path = Path(str(snap.get("log_path") or ""))
        state = {"tail_kb": max(0, min(tail_kb, 4096))}
        attached = asyncio.Event()
        gone = asyncio.Event()

        # The socket stays open while the reader is looking at another screen,
        # and nothing is tailed until it says it is watching
        async def take_commands():
            try:
                while True:
                    command = await websocket.receive_json()
                    action = str(command.get("action") or "")
                    if action == "attach":
                        raw = command.get("tail_kb")
                        if raw is not None:
                            with contextlib.suppress(TypeError, ValueError):
                                state["tail_kb"] = max(0, min(int(raw), 4096))
                        attached.set()
                    elif action == "detach":
                        attached.clear()
            except Exception:
                gone.set()
                attached.set()

        commands = asyncio.create_task(take_commands())
        try:
            await websocket.send_json({"type": "ready"})
            while not gone.is_set():
                await attached.wait()
                if gone.is_set():
                    break

                # Each attach starts from the tail: the reader wants the end of
                # the log, not whatever was current when the socket opened
                pos = await asyncio.to_thread(_tail_log_start_pos, log_path, state["tail_kb"])
                delay = _LOG_POLL_MIN_SEC
                status_at = 0.0
                while attached.is_set() and not gone.is_set():
                    chunk, pos = await asyncio.to_thread(_read_log_chunk, log_path, pos)
                    if chunk:
                        await websocket.send_json({"type": "chunk", "chunk": chunk})
                        # Output comes in bursts, so stay fast while it lasts and
                        # back off once the process falls quiet
                        delay = _LOG_POLL_MIN_SEC
                    else:
                        delay = min(delay + _LOG_POLL_STEP_SEC, _LOG_POLL_MAX_SEC)

                    # Status lives in the database, and asking for it as often as
                    # the file is read would cost more than the read itself
                    now = time.monotonic()
                    if now - status_at >= _LOG_STATUS_INTERVAL_SEC:
                        status_at = now
                        current = await asyncio.to_thread(_get_job_log_snapshot, job_id)
                        status = str(current.get("status") or "")

                        if status in _TERMINAL_JOB_STATES:
                            # Drain whatever the process wrote between the last read and exit
                            tail, pos = await asyncio.to_thread(_read_log_chunk, log_path, pos)
                            if tail:
                                await websocket.send_json({"type": "chunk", "chunk": tail})
                            await websocket.send_json({"type": "done", "status": status})
                            return

                    await asyncio.sleep(delay)
        finally:
            commands.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await commands
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/logs")
async def stream_logs(job_id: str, db: Session = Depends(get_db)):
    job = db.get(BuildJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if not job.log_path:
        raise HTTPException(404, "Log file not available yet")

    log_path = Path(job.log_path)

    async def event_generator():
        pos = 0
        while True:
            chunk, pos = await asyncio.to_thread(_read_log_chunk, log_path, pos)
            if chunk:
                for line in chunk.splitlines():
                    yield f"data: {line}\n\n"

            current = await asyncio.to_thread(_get_job_log_snapshot, job_id)
            status = str(current.get("status") or "")
            if status in _TERMINAL_JOB_STATES:
                yield "event: done\ndata: build_finished\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
