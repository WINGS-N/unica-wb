import asyncio
import hashlib
import json
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from redis.exceptions import RedisError
from rq.exceptions import NoSuchJobError
from rq.job import Job
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from .config import settings
from .cleanup import cleanup_stale_build_overrides
from .database import Base, SessionLocal, engine, get_db, run_migrations
from .debloat_utils import parse_unica_debloat_entries
from .firmware_progress import PROGRESS_CHANNEL, clear_progress, list_progress
from .mods_archive import (
    ModsArchiveError,
    load_upload_meta,
    new_upload_id,
    save_upload_meta,
    upload_archive_path,
    validate_mods_archive,
)
from .models import BuildJob
from .queue import build_queue, control_queue, redis_conn
from .schemas import BuildJobCreate, BuildJobRead, StopJobRequest
from .tasks import (
    run_build_job,
    run_delete_samsung_fw_job,
    run_extract_samsung_fw_job,
    run_stop_job_task,
)

app = FastAPI(title=settings.app_name)


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


def _parse_model_csc(firmware_value: str) -> tuple[str, str]:
    parts = (firmware_value or "").split("/")
    if len(parts) < 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def _get_latest_firmware(model: str, csc: str) -> str:
    # Берем latest версию прямо с Samsung version.xml, fallback empty string если сеть/формат недоступны.
    if not model or not csc:
        return ""
    url = f"https://fota-cloud-dn.ospserver.net/firmware/{csc}/{model}/version.xml"
    try:
        with urlopen(url, timeout=4) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except (URLError, TimeoutError, OSError):
        return ""
    m = re.search(r"<latest[^>]*>(.*?)</latest>", body)
    return (m.group(1).strip() if m else "")


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


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


def _make_firmware_status(firmware_value: str, cache_items: list[dict[str, str | int | bool]]) -> dict[str, str | bool]:
    # Формируем status для верхних карточек source/target с флагом up_to_date.
    model, csc = _parse_model_csc(firmware_value)
    latest = _get_latest_firmware(model, csc)
    key = f"{model}_{csc}" if model and csc else ""
    entry = next((x for x in cache_items if x.get("key") == key), None)
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
def on_startup():
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.logs_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    run_migrations()
    cleaned = cleanup_stale_build_overrides()
    clear_progress()
    print(
        f"[startup] cleanup: removed {cleaned['uploaded_mod_dirs']} uploaded mod override dirs, "
        f"{cleaned['tmp_extra_mods_dirs']} temp extra-mod dirs",
        flush=True,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get(f"{settings.api_prefix}/healthz")
def healthz():
    try:
        redis_conn.ping()
    except RedisError as exc:
        return JSONResponse(status_code=503, content={"status": "down", "redis": str(exc)})
    return {"status": "ok"}


@app.get(f"{settings.api_prefix}/readyz")
def readyz(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        redis_conn.ping()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "down", "reason": str(exc)})
    return {"status": "ready"}


@app.post(f"{settings.api_prefix}/jobs", response_model=BuildJobRead)
def create_job(payload: BuildJobCreate, db: Session = Depends(get_db)):
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
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    q_job = build_queue.enqueue(run_build_job, job.id, job_timeout="12h", result_ttl=86400)
    job.queue_job_id = q_job.id
    db.commit()
    db.refresh(job)
    return job


@app.get(f"{settings.api_prefix}/defaults")
def get_defaults(target: str | None = None, db: Session = Depends(get_db)):
    # Этот endpoint кормит почти весь UI: target list, defaults, commit info, firmware statuses.
    targets = _get_targets()
    target_options = _get_target_options()
    selected_target = target
    if not selected_target:
        selected_target = "b0s" if "b0s" in targets else (targets[0] if targets else "")
    defaults = _get_defaults_for_target(selected_target) if selected_target else {}
    fw_info = _collect_samsung_fw()
    source_firmware = str(defaults.get("source_firmware", ""))
    target_firmware = str(defaults.get("target_firmware", ""))
    source_status = _make_firmware_status(source_firmware, fw_info["items"])
    target_status = _make_firmware_status(target_firmware, fw_info["items"])
    commit_details = _resolve_commit_details()
    repo_sync = _repo_sync_status(_resolve_un1ca_root_path(), str(commit_details.get("branch") or ""))
    root = _resolve_un1ca_root_path()
    return {
        "targets": targets,
        "target_options": target_options,
        "target": selected_target,
        "defaults": defaults,
        "current_commit": commit_details.get("short_hash") or _resolve_source_commit(),
        "current_commit_subject": commit_details.get("subject") or _resolve_source_commit_subject(),
        "current_commit_details": commit_details,
        "latest_artifact_available": _target_has_latest_artifact(db, selected_target),
        "repo_sync": repo_sync,
        "firmware_status": source_status,
        "target_firmware_status": target_status,
        "repo_root": str(root) if root else "",
    }


@app.post(f"{settings.api_prefix}/repo/pull")
def repo_pull():
    return _run_repo_pull()


@app.get(f"{settings.api_prefix}/debloat/options")
def get_debloat_options():
    root = _resolve_un1ca_root_path() or Path(settings.un1ca_root)
    entries = parse_unica_debloat_entries(root)
    return {"entries": entries}


@app.get(f"{settings.api_prefix}/firmware/samsung")
def get_samsung_fw():
    # Данные для модалки Samsung FW: кэш, размеры, latest version, update_available.
    items = _collect_samsung_fw()["items"]
    progress = list_progress()
    for item in items:
        model = str(item.get("model") or "")
        csc = str(item.get("csc") or "")
        latest = _get_latest_firmware(model, csc)
        item["latest_version"] = latest
        downloaded = str(item.get("odin_version") or "")
        extracted = str(item.get("fw_version") or "")
        item["update_available"] = bool(latest and downloaded and downloaded != latest and extracted != latest)
        item["progress"] = progress.get(str(item.get("key") or ""))
    return {"items": items}


@app.websocket(f"{settings.api_prefix}/firmware/progress/ws")
async def stream_firmware_progress_ws(websocket: WebSocket):
    await websocket.accept()
    pubsub = redis_conn.pubsub(ignore_subscribe_messages=True)
    try:
        await websocket.send_json({"type": "snapshot", "items": list(list_progress().values())})
        pubsub.subscribe(PROGRESS_CHANNEL)
        while True:
            message = pubsub.get_message(timeout=1.0)
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
            pubsub.close()
        except Exception:
            pass


@app.delete(f"{settings.api_prefix}/firmware/samsung/{{fw_type}}/{{fw_key}}", response_model=BuildJobRead)
def delete_samsung_fw_entry(fw_type: str, fw_key: str, target: str | None = None, db: Session = Depends(get_db)):
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
    q_job = build_queue.enqueue(run_delete_samsung_fw_job, op_job.id, fw_type, fw_key, job_timeout="2h", result_ttl=3600)
    op_job.queue_job_id = q_job.id
    db.commit()
    db.refresh(op_job)
    return op_job


@app.post(f"{settings.api_prefix}/firmware/samsung/{{fw_key}}/extract", response_model=BuildJobRead)
def extract_samsung_fw(fw_key: str, target: str | None = None, db: Session = Depends(get_db)):
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
    q_job = build_queue.enqueue(run_extract_samsung_fw_job, op_job.id, fw_key, selected_target, job_timeout="4h", result_ttl=3600)
    op_job.queue_job_id = q_job.id
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
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    items = db.query(BuildJob).order_by(desc(BuildJob.created_at)).limit(min(max(limit, 1), 200)).all()
    return items


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", response_model=BuildJobRead)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(BuildJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}/artifact")
def download_artifact(job_id: str, db: Session = Depends(get_db)):
    job = db.get(BuildJob, job_id)
    if not job or not job.artifact_path:
        raise HTTPException(404, "Artifact not found")

    p = Path(job.artifact_path)
    if not p.exists():
        raise HTTPException(404, "Artifact file is missing")

    return FileResponse(path=p, filename=p.name, media_type="application/zip")


@app.get(f"{settings.api_prefix}/artifacts/latest/{{target}}")
def download_latest_artifact_for_target(target: str, db: Session = Depends(get_db)):
    # Берем последний успешный/reused artifact по target для кнопки Latest ZIP.
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

    return FileResponse(path=p, filename=p.name, media_type="application/zip")


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/stop", response_model=BuildJobRead)
def stop_job(job_id: str, payload: StopJobRequest | None = None, db: Session = Depends(get_db)):
    # Stop running job идет в control queue, потому что signal должен отправлять worker (same PID namespace).
    job = db.get(BuildJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status in {"succeeded", "failed", "reused", "canceled"}:
        return job

    signal_type = payload.signal_type if payload else "sigterm"

    if job.status == "queued":
        if job.queue_job_id:
            try:
                rq_job = Job.fetch(job.queue_job_id, connection=redis_conn)
                rq_job.cancel()
            except NoSuchJobError:
                pass
            except Exception:
                pass
        job.status = "canceled"
        job.error = "Build canceled by user (queued job)"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job

    # Running jobs are stopped from worker-side control queue to avoid PID namespace issues in API container.
    control_queue.enqueue(run_stop_job_task, job.id, signal_type, job_timeout="10m", result_ttl=600)
    job.error = f"Stop requested by user ({signal_type.upper()})"
    db.commit()
    db.refresh(job)
    return job


@app.websocket(f"{settings.api_prefix}/jobs/{{job_id}}/ws")
async def stream_logs_ws(websocket: WebSocket, job_id: str, tail_kb: int = 256):
    await websocket.accept()
    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            await websocket.send_json({"type": "error", "message": "Job not found"})
            await websocket.close(code=1008)
            return

        if not job.log_path:
            await websocket.send_json({"type": "error", "message": "Log file not available yet"})
            await websocket.close(code=1008)
            return

        log_path = Path(job.log_path)
        pos = 0
        tail_kb = max(0, min(tail_kb, 4096))
        if log_path.exists() and tail_kb > 0:
            size = log_path.stat().st_size
            pos = max(0, size - (tail_kb * 1024))
            if pos > 0:
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    _ = f.readline()
                    pos = f.tell()
        while True:
            current = db.get(BuildJob, job_id)
            if log_path.exists():
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                    if chunk:
                        await websocket.send_json({"type": "chunk", "chunk": chunk})

            if current and current.status in {"succeeded", "failed", "canceled"}:
                await websocket.send_json({"type": "done", "status": current.status})
                break

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        db.close()


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
            current = db.get(BuildJob, job_id)
            if log_path.exists():
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                    if chunk:
                        for line in chunk.splitlines():
                            yield f"data: {line}\n\n"

            if current and current.status in {"succeeded", "failed", "canceled"}:
                yield "event: done\ndata: build_finished\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
