import asyncio
import base64
import concurrent.futures
import os
import hashlib
import hmac
import json
import re
import secrets
import shlex
import shutil
import subprocess
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from .config import settings
from .cleanup import cleanup_stale_build_overrides
from .database import Base, SessionLocal, engine, get_db, run_migrations
from .debloat_utils import parse_unica_debloat_entries
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
from .error_hints import detect_build_hints
from .mods_utils import parse_unica_mod_entries
from .firmware_progress import PROGRESS_CHANNEL, clear_progress, list_progress
from .mods_archive import (
    ModsArchiveError,
    load_upload_meta,
    new_upload_id,
    save_upload_meta,
    upload_archive_path,
    validate_mods_archive,
)
from .models import AppSetting, BuildJob
from .queue import ARQ_QUEUE_BUILDS, ARQ_QUEUE_CONTROLS, close_arq_pool, get_arq_pool, redis_conn
from .repo_progress import PROGRESS_CHANNEL as REPO_PROGRESS_CHANNEL
from .repo_progress import clear_progress as clear_repo_progress
from .repo_progress import get_progress as get_repo_progress
from .schemas import BuildJobCreate, BuildJobRead, RepoConfigUpdate, StopJobRequest
from .build_progress import (
    PROGRESS_CHANNEL as BUILD_PROGRESS_CHANNEL,
    list_progress as list_build_progress,
    remove_progress as remove_build_progress,
)

app = FastAPI(title=settings.app_name)

_FIRMWARE_LATEST_TIMEOUT_SEC = 10.0
_FIRMWARE_LATEST_TTL_SEC = 3600.0
_FIRMWARE_LATEST_RETRY_SEC = 60.0
_FW_CACHE_KEY_PREFIX = "un1ca:cache:fw_latest:"
_FW_STATS_KEY = "un1ca:cache:fw_latest:stats"
_DIR_SIZE_TTL_SEC = 1200.0
_DIR_CACHE_KEY_PREFIX = "un1ca:cache:dir_size:"
_DIR_STATS_KEY = "un1ca:cache:dir_size:stats"
_REPO_INFO_TTL_SEC = 30.0
_REPO_INFO_KEY = "un1ca:cache:repo_info:v1"
_GIT_SNAPSHOT_TTL_SEC = 30.0
_GIT_SNAPSHOT_KEY = "un1ca:cache:git_snapshot:v1"
_HTTP_METRICS_PREFIX = "un1ca:metrics:http:"
_HTTP_LAT_BUCKETS_MS = [10, 25, 50, 100, 200, 350, 500, 750, 1000, 2000, 5000]


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.endswith("/healthz") or path.endswith("/readyz"):
        return await call_next(request)
    if path.startswith(f"{settings.api_prefix}/auth/"):
        return await call_next(request)
    db = SessionLocal()
    try:
        if not _auth_enabled(db):
            return await call_next(request)
        token = _get_token_from_request(request)
        if not token or not _verify_token(_get_auth_secret(db), token):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    finally:
        db.close()
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


def _invalidate_repo_caches():
    _redis_del(_REPO_INFO_KEY)
    _redis_del(_GIT_SNAPSHOT_KEY)


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
    ms = max(0, int(round(latency_ms)))
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


def _resolve_un1ca_root_path() -> Path | None:
    # Ищем корень UN1CA по сигнатуре каталогов, чтобы API работал и с bind-mount, и с volume clone.
    candidates = [Path(settings.un1ca_root), Path("/workspace/UN1CA"), Path("/workspace")]
    for root in candidates:
        if (root / "target").is_dir() and (root / "unica" / "configs" / "version.sh").is_file():
            return root
    return None


def _read_var_from_shell_file(path: Path, var_name: str) -> str | None:
    # Читаем простые VAR=... из shell-файлов без source/exec, lightweight parse for config defaults.
    if not path.exists():
        return None
    pattern = re.compile(rf'^\s*{re.escape(var_name)}\s*=\s*"?([^"\n#]+)"?')
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line.strip())
        if match:
            return match.group(1).strip()
    return None


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


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
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
    sig = hmac.new(bytes.fromhex(secret_hex), raw, hashlib.sha256).digest()
    return f"{_b64url_encode(raw)}.{_b64url_encode(sig)}"


def _verify_token(secret_hex: str, token: str) -> bool:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        raw = _b64url_decode(payload_b64)
        expected = hmac.new(bytes.fromhex(secret_hex), raw, hashlib.sha256).digest()
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


def _git_url_with_auth(url: str, username: str, token: str) -> str:
    if not url.startswith("http"):
        return url
    if not token:
        return url
    user = username or "oauth2"
    return re.sub(r"^https?://", lambda m: f"{m.group(0)}{user}:{token}@", url, count=1)


def _repo_root() -> Path:
    base = Path(settings.un1ca_root)
    nested = base / "UN1CA"
    if (base / ".git").is_dir() or (base / "target").is_dir():
        return base
    if (nested / ".git").is_dir() or (nested / "target").is_dir():
        return nested
    return base


def _repo_exists() -> bool:
    return (_repo_root() / ".git").is_dir()


def _repo_size_bytes() -> int:
    return _dir_size_bytes(_repo_root())


def _parse_model_csc(firmware_value: str) -> tuple[str, str]:
    parts = (firmware_value or "").split("/")
    if len(parts) < 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def _require_ws_auth(websocket: WebSocket):
    db = SessionLocal()
    try:
        if not _auth_enabled(db):
            return True
        token = websocket.query_params.get("token", "")
        auth = websocket.headers.get("authorization") or websocket.headers.get("Authorization") or ""
        if not token and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        if not token or not _verify_token(_get_auth_secret(db), token):
            return False
        return True
    finally:
        db.close()


def _get_latest_firmware(model: str, csc: str) -> str:
    # Берем latest версию с Samsung version.xml, но с TTL-кэшем и stale fallback.
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
        _redis_set_json(redis_key, {
            "value": "",
            "fetched_at": 0.0,
            "attempted_at": now,
        })
        return ""
    m = re.search(r"<latest[^>]*>(.*?)</latest>", body)
    latest = (m.group(1).strip() if m else "")
    _redis_set_json(redis_key, {
        "value": latest,
        "fetched_at": now if latest else 0.0,
        "attempted_at": now,
    })
    return latest


def _dir_size_bytes(path: Path) -> int:
    cache_key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
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
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    _redis_set_json(redis_key, {"ts": now, "size": total})
    return total


def _collect_resources() -> dict:
    load1, load5, load15 = os.getloadavg()
    mem_total = 0
    mem_available = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024
    except Exception:
        pass
    mem_used = max(0, mem_total - mem_available)
    out_usage = shutil.disk_usage(settings.out_dir) if Path(settings.out_dir).exists() else shutil.disk_usage("/")
    data_usage = shutil.disk_usage(settings.data_dir) if Path(settings.data_dir).exists() else shutil.disk_usage("/")
    return {
        "load": {"1m": load1, "5m": load5, "15m": load15},
        "memory": {"total": mem_total, "used": mem_used, "available": mem_available},
        "disk": {
            "out": {"total": out_usage.total, "used": out_usage.used, "free": out_usage.free},
            "data": {"total": data_usage.total, "used": data_usage.used, "free": data_usage.free},
        },
    }


def _collect_samsung_fw() -> dict[str, list[dict[str, str | int | bool]]]:
    # Собираем Odin/FW кэш в единый список карточек по ключу MODEL_CSC.
    out_root = Path(settings.out_dir)
    odin_root = out_root / "odin"
    fw_root = out_root / "fw"
    rows: dict[str, dict[str, str | int | bool]] = {}

    if odin_root.is_dir():
        for d in sorted([x for x in odin_root.iterdir() if x.is_dir()], key=lambda x: x.name):
            model, csc = (d.name.split("_", 1) + [""])[:2] if "_" in d.name else (d.name, "")
            key = f"{model}_{csc}" if csc else model
            rows.setdefault(
                key,
                {
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
                },
            )
            rows[key]["has_odin"] = True
            rows[key]["odin_size_bytes"] = _dir_size_bytes(d)
            marker = d / ".downloaded"
            if marker.exists():
                rows[key]["odin_version"] = marker.read_text(encoding="utf-8", errors="ignore").strip()

    if fw_root.is_dir():
        for d in sorted([x for x in fw_root.iterdir() if x.is_dir()], key=lambda x: x.name):
            model, csc = (d.name.split("_", 1) + [""])[:2] if "_" in d.name else (d.name, "")
            key = f"{model}_{csc}" if csc else model
            rows.setdefault(
                key,
                {
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
                },
            )
            rows[key]["has_fw"] = True
            rows[key]["fw_size_bytes"] = _dir_size_bytes(d)
            marker = d / ".extracted"
            if marker.exists():
                rows[key]["fw_version"] = marker.read_text(encoding="utf-8", errors="ignore").strip()

    return {"items": sorted(rows.values(), key=lambda x: str(x.get("key", "")))}


def _fill_latest_for_fw_items(items: list[dict[str, str | int | bool]]):
    # Resolve latest firmware in parallel to avoid N sequential network waits on first load.
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
    # Формируем status для верхних карточек source/target с флагом up_to_date.
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


def _get_targets() -> list[str]:
    project_root = _resolve_un1ca_root_path()
    if not project_root:
        return []
    root = project_root / "target"
    if not root.is_dir():
        return []
    return sorted([d.name for d in root.iterdir() if d.is_dir()])


def _get_target_options() -> list[dict[str, str]]:
    root = _resolve_un1ca_root_path()
    if not root:
        return []
    options = []
    for d in sorted([x for x in (root / "target").iterdir() if x.is_dir()], key=lambda x: x.name):
        target_name = _read_var_from_shell_file(d / "config.sh", "TARGET_NAME") or d.name
        options.append({"code": d.name, "name": target_name})
    return options


def _get_defaults_for_target(target: str) -> dict[str, str | int]:
    root = _resolve_un1ca_root_path() or Path(settings.un1ca_root)
    source_firmware = _read_var_from_shell_file(root / "unica" / "configs" / "essi.sh", "SOURCE_FIRMWARE") or ""
    target_firmware = _read_var_from_shell_file(root / "target" / target / "config.sh", "TARGET_FIRMWARE") or ""
    version_major = int(_read_var_from_shell_file(root / "unica" / "configs" / "version.sh", "VERSION_MAJOR") or 0)
    version_minor = int(_read_var_from_shell_file(root / "unica" / "configs" / "version.sh", "VERSION_MINOR") or 0)
    version_patch = int(_read_var_from_shell_file(root / "unica" / "configs" / "version.sh", "VERSION_PATCH") or 0)
    return {
        "source_firmware": source_firmware,
        "target_firmware": target_firmware,
        "version_major": version_major,
        "version_minor": version_minor,
        "version_patch": version_patch,
        "version_suffix": "",
    }


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
    target: str,
    source_firmware: str,
    target_firmware: str,
) -> dict[str, object]:
    root = _resolve_un1ca_root_path() or Path(settings.un1ca_root)
    out_root = Path(settings.out_dir)
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
    # Сигнатура сборки нужна для reuse готового ZIP без повторной сборки.
    payload = "|".join(
        [
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
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def _resolve_source_commit() -> str:
    # Git может ругаться на ownership в контейнере, поэтому всегда safe.directory=*.
    root = _resolve_un1ca_root_path()
    if not root:
        return settings.source_commit or "unknown"
    try:
        out = subprocess.check_output(
            ["git", "-c", "safe.directory=*", "-C", str(root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return out
    except Exception:  # noqa: BLE001
        pass
    return settings.source_commit or "unknown"


def _create_operation_job(db: Session, *, target: str, operation_name: str) -> BuildJob:
    # Operation jobs (extract/delete/stop) показываем в том же списке jobs, чтобы UI был единый.
    job = BuildJob(
        job_kind="operation",
        operation_name=operation_name,
        target=target,
        source_commit=_resolve_source_commit(),
        force=False,
        no_rom_zip=False,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _resolve_source_commit_subject() -> str:
    root = _resolve_un1ca_root_path()
    if not root:
        return ""
    try:
        out = subprocess.check_output(
            ["git", "-c", "safe.directory=*", "-C", str(root), "log", "-1", "--pretty=%s"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out
    except Exception:  # noqa: BLE001
        return ""


def _resolve_commit_details() -> dict[str, str]:
    # Подробности коммита для модалки Current Commit.
    root = _resolve_un1ca_root_path()
    if not root:
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
    try:
        branch = subprocess.check_output(
            ["git", "-c", "safe.directory=*", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        branch = ""
    try:
        fmt = "%H%n%h%n%s%n%b%n%an%n%ae%n%cn%n%ce"
        raw = subprocess.check_output(
            ["git", "-c", "safe.directory=*", "-C", str(root), "log", "-1", f"--pretty={fmt}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
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
    except Exception:
        return {
            "branch": branch,
            "short_hash": settings.source_commit or "unknown",
            "full_hash": "",
            "subject": "",
            "body": "",
            "author_name": "",
            "author_email": "",
            "committer_name": "",
            "committer_email": "",
        }


def _repo_sync_status(root: Path, branch: str) -> dict[str, str | int]:
    # Считаем ahead/behind относительно origin/<branch> для цветового статуса в UI.
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
            ["git", "-c", "safe.directory=*", "-C", str(root), "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        left, right = (counts.split() + ["0", "0"])[:2]
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


def _git_snapshot_cached() -> dict[str, dict]:
    cached = _redis_get_json(_GIT_SNAPSHOT_KEY)
    if cached and isinstance(cached.get("commit"), dict) and isinstance(cached.get("repo_sync"), dict):
        return cached
    if not _repo_exists():
        payload = {
            "commit": {
                "branch": "",
                "short_hash": settings.source_commit or "unknown",
                "full_hash": "",
                "subject": "",
                "body": "",
                "author_name": "",
                "author_email": "",
                "committer_name": "",
                "committer_email": "",
            },
            "repo_sync": {
                "state": "unknown",
                "ahead_by": 0,
                "behind_by": 0,
                "remote_ref": "",
            },
        }
    else:
        repo_root = _repo_root()
        commit_details = _resolve_commit_details()
        repo_sync = _repo_sync_status(repo_root, str(commit_details.get("branch") or ""))
        payload = {"commit": commit_details, "repo_sync": repo_sync}
    _redis_set_json(_GIT_SNAPSHOT_KEY, payload)
    try:
        redis_conn.expire(_GIT_SNAPSHOT_KEY, int(_GIT_SNAPSHOT_TTL_SEC))
    except Exception:
        pass
    return payload


def _repo_info(db: Session) -> dict[str, str | int | bool | dict]:
    cached = _redis_get_json(_REPO_INFO_KEY)
    if cached and isinstance(cached.get("git_url"), str):
        return cached

    repo_root = _repo_root()
    git_url = _get_setting(db, "repo.git_url", settings.repo_url_default)
    git_ref = _get_setting(db, "repo.git_ref", settings.repo_ref_default)
    git_username = _get_setting(db, "repo.git_username", "")
    git_token = _get_setting(db, "repo.git_token", "")
    snapshot = _git_snapshot_cached()
    commit_details = snapshot.get("commit", {})
    repo_sync = snapshot.get("repo_sync", {})
    payload = {
        "git_url": git_url,
        "git_ref": git_ref,
        "repo_path": str(repo_root),
        "repo_exists": _repo_exists(),
        "repo_size_bytes": _repo_size_bytes(),
        "git_username": git_username,
        "git_token_set": bool(git_token),
        "commit": commit_details,
        "repo_sync": repo_sync,
        "progress": get_repo_progress(),
    }
    _redis_set_json(_REPO_INFO_KEY, payload)
    try:
        redis_conn.expire(_REPO_INFO_KEY, int(_REPO_INFO_TTL_SEC))
    except Exception:
        pass
    return payload


def _repo_info_with_new_session() -> dict[str, str | int | bool | dict]:
    db = SessionLocal()
    try:
        return _repo_info(db)
    finally:
        db.close()


def _run_repo_pull() -> dict[str, str | int]:
    # Без merge-commit: pull только fast-forward, then sync/update submodules.
    root = _resolve_un1ca_root_path()
    if not root:
        raise HTTPException(400, "Repository root is not available")
    details = _resolve_commit_details()
    branch = str(details.get("branch") or "").strip()
    if not branch or branch == "HEAD":
        raise HTTPException(400, "Detached HEAD: checkout a branch before pull")

    cmd = (
        f"cd {shlex.quote(str(root))} && "
        f"git -c safe.directory=* fetch --all --tags --prune && "
        f"git -c safe.directory=* pull --ff-only origin {shlex.quote(branch)} && "
        "git -c safe.directory=* submodule sync --recursive && "
        "git -c safe.directory=* submodule update --init --recursive --jobs 8"
    )
    try:
        subprocess.check_output(["bash", "-lc", cmd], stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(409, f"Pull failed: {(exc.output or '').strip()}") from exc

    updated = _resolve_commit_details()
    return {"commit": updated, "repo_sync": _repo_sync_status(root, str(updated.get('branch') or ''))}


def _normalize_path_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = (raw or "").strip()
        if not item or item in seen:
            continue
        # Keep this simple: debloat values are plain partition-relative paths.
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
    cleaned = await asyncio.to_thread(cleanup_stale_build_overrides)
    clear_progress()
    clear_repo_progress()
    _invalidate_repo_caches()
    await get_arq_pool()
    print(
        f"[startup] cleanup: removed {cleaned['uploaded_mod_dirs']} uploaded mod override dirs, "
        f"{cleaned['tmp_extra_mods_dirs']} temp extra-mod dirs",
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


def _target_has_latest_artifact(db: Session, target: str) -> bool:
    # Кнопка Latest ZIP должна быть active только если файл реально существует на диске.
    if not target:
        return False
    job = (
        db.query(BuildJob)
        .filter(
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


def _target_has_latest_artifact_with_new_session(target: str) -> bool:
    db = SessionLocal()
    try:
        return _target_has_latest_artifact(db, target)
    finally:
        db.close()


def _list_jobs_with_new_session(limit: int) -> list[BuildJob]:
    db = SessionLocal()
    try:
        return db.query(BuildJob).order_by(desc(BuildJob.created_at)).limit(min(max(limit, 1), 200)).all()
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


def _get_latest_artifact_path_for_target_with_new_session(target: str) -> Path:
    db = SessionLocal()
    try:
        if target not in _get_targets():
            raise HTTPException(400, "Unknown target")
        job = (
            db.query(BuildJob)
            .filter(
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


def _list_artifacts_with_new_session(target: str | None = None, limit: int = 50) -> list[dict]:
    db = SessionLocal()
    try:
        q = (
            db.query(BuildJob)
            .filter(
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
            if job.artifact_path and Path(job.artifact_path).exists():
                size = Path(job.artifact_path).stat().st_size
            items.append(
                {
                    "job_id": job.id,
                    "target": job.target,
                    "artifact_path": job.artifact_path,
                    "size_bytes": size,
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


def _update_repo_config_with_new_session(
    git_url: str,
    git_username: str | None = None,
    git_token: str | None = None,
) -> dict[str, str | int | bool | dict]:
    db = SessionLocal()
    try:
        _set_setting(db, "repo.git_url", git_url)
        if git_username is not None:
            _set_setting(db, "repo.git_username", git_username.strip())
        if git_token is not None:
            if git_token.strip():
                _set_setting(db, "repo.git_token", git_token.strip())
            else:
                _delete_setting(db, "repo.git_token")
        _invalidate_repo_caches()
        return _repo_info(db)
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
    try:
        await asyncio.to_thread(redis_conn.ping)
    except RedisError as exc:
        return JSONResponse(status_code=503, content={"status": "down", "redis": str(exc)})
    return {"status": "ok"}


@app.get(f"{settings.api_prefix}/readyz")
async def readyz():
    try:
        return await asyncio.to_thread(_readyz_impl)
    except Exception as exc:  # noqa: BLE001
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
    if _hash_password(password, salt) != secret:
        raise HTTPException(401, "Invalid password")
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
        return {"enabled": False}
    salt = secrets.token_hex(16)
    hashed = _hash_password(password, salt)
    _set_setting(db, "auth.salt", salt)
    _set_setting(db, "auth.hash", hashed)
    return {"enabled": True, "token": _make_token(hashed)}


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
            "repo_info_cached": bool(_redis_get_json(_REPO_INFO_KEY)),
            "git_snapshot_cached": bool(_redis_get_json(_GIT_SNAPSHOT_KEY)),
        },
        "http_metrics": {
            "storage": "redis",
            "endpoints": http_metrics,
        },
    }


@app.get(f"{settings.api_prefix}/system/resources")
async def system_resources():
    return await asyncio.to_thread(_collect_resources)


@app.get(f"{settings.api_prefix}/debug/perf/top")
async def debug_perf_top(limit: int = 10, sort_by: str = "p95"):
    if sort_by not in {"p95", "avg"}:
        raise HTTPException(400, "sort_by must be p95 or avg")
    top = await asyncio.to_thread(_http_metrics_top, limit, sort_by)
    return {"sort_by": sort_by, "limit": max(1, min(limit, 100)), "items": top}


@app.post(f"{settings.api_prefix}/jobs", response_model=BuildJobRead)
async def create_job(payload: BuildJobCreate, db: Session = Depends(get_db)):
    # Главный endpoint постановки build job: defaults -> signature -> reuse или новая очередь.
    source_commit = _resolve_source_commit()
    if payload.target not in _get_targets():
        raise HTTPException(400, "Unknown target")
    defaults = _get_defaults_for_target(payload.target)
    source_firmware = payload.source_firmware or str(defaults["source_firmware"])
    target_firmware = payload.target_firmware or str(defaults["target_firmware"])
    version_major = payload.version_major if payload.version_major is not None else int(defaults["version_major"])
    version_minor = payload.version_minor if payload.version_minor is not None else int(defaults["version_minor"])
    version_patch = payload.version_patch if payload.version_patch is not None else int(defaults["version_patch"])
    version_suffix = (payload.version_suffix if payload.version_suffix is not None else str(defaults["version_suffix"])).strip()
    extra_mods_signature = ""
    extra_mods_archive_path = None
    extra_mods_modules_json = None
    if payload.extra_mods_upload_id:
        meta = load_upload_meta(settings.data_dir, payload.extra_mods_upload_id)
        if not meta:
            raise HTTPException(400, "Invalid extra_mods_upload_id")
        if meta.get("used"):
            raise HTTPException(400, "This uploaded mods archive has already been used")
        archive_path = meta.get("archive_path")
        if not archive_path or not Path(archive_path).exists():
            raise HTTPException(400, "Uploaded mods archive file is missing")
        meta["used"] = True
        save_upload_meta(settings.data_dir, payload.extra_mods_upload_id, meta)
        extra_mods_archive_path = archive_path
        modules = meta.get("modules", [])
        extra_mods_modules_json = json.dumps(modules, ensure_ascii=True)
        extra_mods_signature = hashlib.sha256(extra_mods_modules_json.encode("utf-8")).hexdigest()[:16]

    debloat_disabled = payload.debloat_disabled or []
    mods_disabled = payload.mods_disabled
    mods_disabled_json = None
    mods_signature = ""
    if mods_disabled is not None:
        valid_mod_ids = {x["id"] for x in parse_unica_mod_entries(_resolve_un1ca_root_path() or Path(settings.un1ca_root))}
        unknown_mods = [x for x in mods_disabled if x not in valid_mod_ids]
        if unknown_mods:
            raise HTTPException(400, f"Unknown mod ids: {', '.join(unknown_mods[:5])}")
        mods_disabled_json = json.dumps(sorted(set(mods_disabled)), ensure_ascii=True)
        mods_signature = hashlib.sha256(mods_disabled_json.encode("utf-8")).hexdigest()[:16]

    valid_debloat_ids = {x["id"] for x in parse_unica_debloat_entries(_resolve_un1ca_root_path() or Path(settings.un1ca_root))}
    if debloat_disabled:
        unknown = [x for x in debloat_disabled if x not in valid_debloat_ids]
        if unknown:
            raise HTTPException(400, f"Unknown debloat ids: {', '.join(unknown[:5])}")
    debloat_add_system = _normalize_path_list(payload.debloat_add_system)
    debloat_add_product = _normalize_path_list(payload.debloat_add_product)
    debloat_disabled_json = json.dumps(sorted(set(debloat_disabled)), ensure_ascii=True)
    debloat_add_system_json = json.dumps(debloat_add_system, ensure_ascii=True)
    debloat_add_product_json = json.dumps(debloat_add_product, ensure_ascii=True)
    debloat_signature = hashlib.sha256(debloat_disabled_json.encode("utf-8")).hexdigest()[:16]
    debloat_add_system_signature = hashlib.sha256(debloat_add_system_json.encode("utf-8")).hexdigest()[:16]
    debloat_add_product_signature = hashlib.sha256(debloat_add_product_json.encode("utf-8")).hexdigest()[:16]
    ff_overrides_json = None
    ff_signature = ""
    if payload.ff_overrides:
        ff_data = _collect_ff_defaults(payload.target, source_firmware, target_firmware)
        valid_ff_keys = {entry["key"] for entry in ff_data.get("entries", []) if entry.get("key")}
        invalid_keys = [k for k in payload.ff_overrides.keys() if k not in valid_ff_keys]
        if invalid_keys:
            raise HTTPException(400, f"Unknown floating feature keys: {', '.join(invalid_keys[:5])}")
        normalized = {k: normalize_ff_value(v) for k, v in payload.ff_overrides.items()}
        ff_overrides_json = json.dumps(normalized, ensure_ascii=True, sort_keys=True)
        ff_signature = hashlib.sha256(ff_overrides_json.encode("utf-8")).hexdigest()[:16]
    build_signature = _build_signature(
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

    # Reuse an already built artifact for the same build signature unless forced.
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
            now = datetime.now(timezone.utc)
            if extra_mods_archive_path:
                try:
                    Path(extra_mods_archive_path).unlink(missing_ok=True)
                except Exception:
                    pass
            job = BuildJob(
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
            return job

    job = BuildJob(
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
    return job


@app.get(f"{settings.api_prefix}/defaults")
async def get_defaults(target: str | None = None):
    # Этот endpoint кормит почти весь UI: target list, defaults, commit info, firmware statuses.
    target_options = await asyncio.to_thread(_get_target_options)
    targets = [str(x.get("code") or "") for x in target_options if x.get("code")]
    selected_target = target
    if not selected_target:
        selected_target = "b0s" if "b0s" in targets else (targets[0] if targets else "")
    defaults = await asyncio.to_thread(_get_defaults_for_target, selected_target) if selected_target else {}
    fw_info = await asyncio.to_thread(_collect_samsung_fw)
    await asyncio.to_thread(_fill_latest_for_fw_items, fw_info["items"])
    source_firmware = str(defaults.get("source_firmware", ""))
    target_firmware = str(defaults.get("target_firmware", ""))
    source_status, target_status = await asyncio.gather(
        asyncio.to_thread(_make_firmware_status, source_firmware, fw_info["items"]),
        asyncio.to_thread(_make_firmware_status, target_firmware, fw_info["items"]),
    )
    repo_info = await asyncio.to_thread(_repo_info_with_new_session)
    commit_details = repo_info.get("commit") if isinstance(repo_info.get("commit"), dict) else {}
    repo_sync = repo_info.get("repo_sync") if isinstance(repo_info.get("repo_sync"), dict) else {}
    root = _resolve_un1ca_root_path()
    return {
        "targets": targets,
        "target_options": target_options,
        "target": selected_target,
        "defaults": defaults,
        "current_commit": commit_details.get("short_hash") or (settings.source_commit or "unknown"),
        "current_commit_subject": commit_details.get("subject") or "",
        "current_commit_details": commit_details,
        "latest_artifact_available": await asyncio.to_thread(_target_has_latest_artifact_with_new_session, selected_target),
        "repo_sync": repo_sync,
        "repo_info": repo_info,
        "firmware_status": source_status,
        "target_firmware_status": target_status,
        "repo_root": str(root) if root else "",
    }


@app.get(f"{settings.api_prefix}/repo/info")
async def repo_info():
    return await asyncio.to_thread(_repo_info_with_new_session)


@app.patch(f"{settings.api_prefix}/repo/config")
async def update_repo_config(payload: RepoConfigUpdate):
    value = (payload.git_url or "").strip()
    if not re.match(r"^(https://|git@|ssh://).+", value):
        raise HTTPException(400, "Invalid git url")
    return await asyncio.to_thread(
        _update_repo_config_with_new_session,
        value,
        payload.git_username,
        payload.git_token,
    )


@app.post(f"{settings.api_prefix}/repo/clone", response_model=BuildJobRead)
async def repo_clone(db: Session = Depends(get_db)):
    git_url = _get_setting(db, "repo.git_url", settings.repo_url_default)
    git_ref = _get_setting(db, "repo.git_ref", settings.repo_ref_default)
    git_username = _get_setting(db, "repo.git_username", "")
    git_token = _get_setting(db, "repo.git_token", "")
    auth_url = _git_url_with_auth(git_url, git_username, git_token)
    op_job = _create_operation_job(db, target="repo", operation_name=f"Repo clone: {_safe_git_url(git_url)}")
    _invalidate_repo_caches()
    op_job.queue_job_id = await _enqueue_build("repo_clone_job_task", op_job.id, auth_url, git_ref, git_username, git_token)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/repo/pull", response_model=BuildJobRead)
async def repo_pull(db: Session = Depends(get_db)):
    git_ref = _get_setting(db, "repo.git_ref", settings.repo_ref_default)
    git_url = _get_setting(db, "repo.git_url", settings.repo_url_default)
    git_username = _get_setting(db, "repo.git_username", "")
    git_token = _get_setting(db, "repo.git_token", "")
    op_job = _create_operation_job(db, target="repo", operation_name=f"Repo pull: {git_ref}")
    _invalidate_repo_caches()
    op_job.queue_job_id = await _enqueue_build("repo_pull_job_task", op_job.id, git_ref, git_url, git_username, git_token)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/repo/submodules", response_model=BuildJobRead)
async def repo_submodules(db: Session = Depends(get_db)):
    git_url = _get_setting(db, "repo.git_url", settings.repo_url_default)
    git_username = _get_setting(db, "repo.git_username", "")
    git_token = _get_setting(db, "repo.git_token", "")
    op_job = _create_operation_job(db, target="repo", operation_name="Repo submodules update")
    _invalidate_repo_caches()
    op_job.queue_job_id = await _enqueue_build("repo_submodules_job_task", op_job.id, git_url, git_username, git_token)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.delete(f"{settings.api_prefix}/repo", response_model=BuildJobRead)
async def repo_delete(mode: str = "repo_only", db: Session = Depends(get_db)):
    if mode not in {"repo_only", "repo_with_out"}:
        raise HTTPException(400, "mode must be repo_only or repo_with_out")
    op_name = "Repo delete (keep out)" if mode == "repo_only" else "Repo delete (with out)"
    op_job = _create_operation_job(db, target="repo", operation_name=op_name)
    _invalidate_repo_caches()
    op_job.queue_job_id = await _enqueue_build("repo_delete_job_task", op_job.id, mode)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.websocket(f"{settings.api_prefix}/repo/progress/ws")
async def stream_repo_progress_ws(websocket: WebSocket):
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    pubsub = redis_conn.pubsub(ignore_subscribe_messages=True)
    try:
        snapshot = await asyncio.to_thread(get_repo_progress)
        await websocket.send_json({"type": "snapshot", "item": snapshot})
        await asyncio.to_thread(pubsub.subscribe, REPO_PROGRESS_CHANNEL)
        while True:
            message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
            if message and message.get("type") == "message":
                data = message.get("data")
                try:
                    payload = json.loads(data.decode("utf-8") if isinstance(data, bytes) else str(data))
                except Exception:
                    payload = {"type": "error", "message": "bad repo progress payload"}
                await websocket.send_json(payload)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await asyncio.to_thread(pubsub.close)
        except Exception:
            pass


@app.get(f"{settings.api_prefix}/debloat/options")
async def get_debloat_options():
    root = _resolve_un1ca_root_path() or Path(settings.un1ca_root)
    entries = await asyncio.to_thread(parse_unica_debloat_entries, root)
    return {"entries": entries}


@app.get(f"{settings.api_prefix}/floating/features")
async def get_floating_features(target: str):
    if target not in _get_targets():
        raise HTTPException(400, "Unknown target")
    defaults = await asyncio.to_thread(_get_defaults_for_target, target)
    source_firmware = str(defaults.get("source_firmware", ""))
    target_firmware = str(defaults.get("target_firmware", ""))
    data = await asyncio.to_thread(_collect_ff_defaults, target, source_firmware, target_firmware)
    return data


@app.get(f"{settings.api_prefix}/mods/options")
async def get_mods_options():
    root = _resolve_un1ca_root_path() or Path(settings.un1ca_root)
    entries = await asyncio.to_thread(parse_unica_mod_entries, root)
    return {"entries": entries}


@app.get(f"{settings.api_prefix}/firmware/samsung")
async def get_samsung_fw():
    # Данные для модалки Samsung FW: кэш, размеры, latest version, update_available.
    items = (await asyncio.to_thread(_collect_samsung_fw))["items"]
    await asyncio.to_thread(_fill_latest_for_fw_items, items)
    progress = list_progress()
    for item in items:
        latest = str(item.get("latest_version") or "")
        item["latest_version"] = latest
        downloaded = str(item.get("odin_version") or "")
        extracted = str(item.get("fw_version") or "")
        item["update_available"] = bool(latest and downloaded and downloaded != latest and extracted != latest)
        item["progress"] = progress.get(str(item.get("key") or ""))
    return {"items": items}


@app.websocket(f"{settings.api_prefix}/firmware/progress/ws")
async def stream_firmware_progress_ws(websocket: WebSocket):
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    pubsub = redis_conn.pubsub(ignore_subscribe_messages=True)
    try:
        progress = await asyncio.to_thread(list_progress)
        await websocket.send_json({"type": "snapshot", "items": list(progress.values())})
        await asyncio.to_thread(pubsub.subscribe, PROGRESS_CHANNEL)
        while True:
            message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
            if message and message.get("type") == "message":
                data = message.get("data")
                try:
                    payload = json.loads(data.decode("utf-8") if isinstance(data, bytes) else str(data))
                except Exception:
                    payload = {"type": "error", "message": "bad firmware progress payload"}
                await websocket.send_json(payload)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await asyncio.to_thread(pubsub.close)
        except Exception:
            pass


@app.websocket(f"{settings.api_prefix}/build/progress/ws")
async def stream_build_progress_ws(websocket: WebSocket):
    await websocket.accept()
    if not _require_ws_auth(websocket):
        await websocket.close(code=4401)
        return
    pubsub = redis_conn.pubsub(ignore_subscribe_messages=True)
    try:
        progress = await asyncio.to_thread(list_build_progress)
        await websocket.send_json({"type": "snapshot", "items": list(progress.values())})
        await asyncio.to_thread(pubsub.subscribe, BUILD_PROGRESS_CHANNEL)
        while True:
            message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
            if message and message.get("type") == "message":
                data = message.get("data")
                try:
                    payload = json.loads(data.decode("utf-8") if isinstance(data, bytes) else str(data))
                except Exception:
                    payload = {"type": "error", "message": "bad build progress payload"}
                await websocket.send_json(payload)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await asyncio.to_thread(pubsub.close)
        except Exception:
            pass


@app.delete(f"{settings.api_prefix}/firmware/samsung/{{fw_type}}/{{fw_key}}", response_model=BuildJobRead)
async def delete_samsung_fw_entry(fw_type: str, fw_key: str, target: str | None = None, db: Session = Depends(get_db)):
    # Удаление делает operation-job через очередь, чтобы action был логируемый и отменяемый.
    if fw_type not in {"odin", "fw"}:
        raise HTTPException(400, "fw_type must be 'odin' or 'fw'")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", fw_key):
        raise HTTPException(400, "Invalid fw key")

    targets = _get_targets()
    selected_target = target or ("b0s" if "b0s" in targets else (targets[0] if targets else ""))
    if not selected_target:
        raise HTTPException(400, "No targets available")
    if selected_target not in targets:
        raise HTTPException(400, "Unknown target")

    base = Path(settings.out_dir) / ("odin" if fw_type == "odin" else "fw")
    fw_path = base / fw_key
    if not fw_path.exists():
        raise HTTPException(404, "FW entry not found")
    if not fw_path.is_dir():
        raise HTTPException(400, "FW entry is not a directory")

    op_job = _create_operation_job(
        db,
        target=selected_target,
        operation_name=f"Delete {fw_type.upper()} FW entry: {fw_key}",
    )
    op_job.queue_job_id = await _enqueue_build("delete_fw_job_task", op_job.id, fw_type, fw_key)
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/firmware/samsung/{{fw_key}}/extract", response_model=BuildJobRead)
async def extract_samsung_fw(fw_key: str, target: str | None = None, db: Session = Depends(get_db)):
    # Extract тоже идет через очередь: heavy I/O, long runtime, нужны логи и статус.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", fw_key):
        raise HTTPException(400, "Invalid fw key")

    targets = _get_targets()
    selected_target = target or ("b0s" if "b0s" in targets else (targets[0] if targets else ""))
    if not selected_target:
        raise HTTPException(400, "No targets available")
    if selected_target not in targets:
        raise HTTPException(400, "Unknown target")

    odin_dir = Path(settings.out_dir) / "odin" / fw_key
    if not odin_dir.is_dir():
        raise HTTPException(404, "ODIN FW entry not found")

    op_job = _create_operation_job(
        db,
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
async def list_jobs(limit: int = 50):
    return await asyncio.to_thread(_list_jobs_with_new_session, limit)


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


@app.get(f"{settings.api_prefix}/artifacts/latest/{{target}}")
async def download_latest_artifact_for_target(target: str):
    # Берем последний успешный/reused artifact по target для кнопки Latest ZIP.
    p = await asyncio.to_thread(_get_latest_artifact_path_for_target_with_new_session, target)
    return FileResponse(path=p, filename=p.name, media_type="application/zip")


@app.get(f"{settings.api_prefix}/artifacts/history")
async def artifacts_history(target: str | None = None, limit: int = 50):
    items = await asyncio.to_thread(_list_artifacts_with_new_session, target, limit)
    return {"items": items}


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/stop", response_model=BuildJobRead)
async def stop_job(job_id: str, payload: StopJobRequest | None = None, db: Session = Depends(get_db)):
    # Stop running job идет в control queue, потому что signal должен отправлять worker (same PID namespace).
    job = db.get(BuildJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status in {"succeeded", "failed", "reused", "canceled"}:
        return job

    signal_type = payload.signal_type if payload else "sigterm"

    if job.status == "queued":
        job.status = "canceled"
        job.error = "Build canceled by user (queued job)"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job

    # Running jobs are stopped from worker-side control queue to avoid PID namespace issues in API container.
    await _enqueue_control("stop_job_task", job.id, signal_type)
    job.error = f"Stop requested by user ({signal_type.upper()})"
    db.commit()
    db.refresh(job)
    return job


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/hints")
async def job_hints(job_id: str):
    job = await asyncio.to_thread(_get_job_with_new_session, job_id)
    if not job or not job.log_path:
        raise HTTPException(404, "Log file not found")
    log_path = Path(job.log_path)
    text = await asyncio.to_thread(_read_log_tail_text, log_path, 512)
    hints = detect_build_hints(text)
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
    text, _ = _read_log_chunk(path, pos)
    return text


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
        tail_kb = max(0, min(tail_kb, 4096))
        pos = await asyncio.to_thread(_tail_log_start_pos, log_path, tail_kb)
        while True:
            chunk, pos = await asyncio.to_thread(_read_log_chunk, log_path, pos)
            if chunk:
                await websocket.send_json({"type": "chunk", "chunk": chunk})

            current = await asyncio.to_thread(_get_job_log_snapshot, job_id)
            status = str(current.get("status") or "")

            if status in {"succeeded", "failed", "canceled"}:
                await websocket.send_json({"type": "done", "status": status})
                break

            await asyncio.sleep(1)
    except WebSocketDisconnect:
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
            if status in {"succeeded", "failed", "canceled"}:
                yield "event: done\ndata: build_finished\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
