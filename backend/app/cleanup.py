import shutil
import time
from pathlib import Path

from . import workspaces as ws_lib
from .config import settings
from .database import SessionLocal

# A clone writes constantly, so anything touched recently is a live attempt
STALE_CLONE_AGE_SEC = 600

RETENTION_ROM_KEY = "retention_rom_zips"
RETENTION_TARGET_FILES_KEY = "retention_target_files"


def _keep_newest(rows, column: str, keep: int) -> int:
    # Rows arrive newest first, so everything past the limit goes
    removed = 0
    for row in rows[keep:]:
        value = getattr(row, column, None)
        if not value:
            continue
        path = Path(str(value))
        if path.is_file():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        setattr(row, column, None)
    return removed


def apply_artifact_retention(keep_rom: int, keep_target_files: int) -> dict[str, int]:
    # Artifacts are reproducible and huge, so only the newest few per target are
    # worth the disk. A job still on the queue keeps its files whatever the limit
    from .models import BuildJob

    result = {"rom_zips": 0, "target_files": 0}
    if keep_rom <= 0 and keep_target_files <= 0:
        return result

    db = SessionLocal()
    try:
        live = {"queued", "running"}
        jobs = (
            db.query(BuildJob)
            .filter(BuildJob.status.notin_(live))
            .order_by(BuildJob.finished_at.desc(), BuildJob.created_at.desc())
            .all()
        )
        by_target: dict[tuple[str, str], list] = {}
        for job in jobs:
            by_target.setdefault((str(job.workspace_id or ""), str(job.target or "")), []).append(job)

        for rows in by_target.values():
            if keep_rom > 0:
                with_rom = [x for x in rows if x.artifact_path]
                result["rom_zips"] += _keep_newest(with_rom, "artifact_path", keep_rom)
            if keep_target_files > 0:
                with_tf = [x for x in rows if x.target_files_path]
                result["target_files"] += _keep_newest(with_tf, "target_files_path", keep_target_files)
        db.commit()
    finally:
        db.close()
    return result


def _newest_mtime(path: Path) -> float:
    newest = path.stat().st_mtime
    for child in path.rglob("*"):
        try:
            newest = max(newest, child.stat().st_mtime)
        except OSError:
            continue
    return newest


def cleanup_stale_build_overrides() -> dict[str, int]:
    cleaned = {
        "uploaded_mod_dirs": 0,
        "tmp_extra_mods_dirs": 0,
        "stale_clone_dirs": 0,
    }

    roots: list[Path] = []
    db = SessionLocal()
    try:
        for ws in ws_lib.list_workspaces(db):
            roots.append(ws_lib.root_path(ws))
    finally:
        db.close()
    if not roots:
        roots.append(Path(settings.un1ca_root))

    for root in roots:
        mods_dir = root / "unica" / "mods"
        if not mods_dir.is_dir():
            continue
        for item in mods_dir.glob(".uploaded-*"):
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            cleaned["uploaded_mod_dirs"] += 1

    tmp_root = Path(settings.data_dir) / "tmp-extra-mods"
    if tmp_root.is_dir():
        for item in tmp_root.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            cleaned["tmp_extra_mods_dirs"] += 1

    # A worker killed mid-clone leaves a .clone-<job> staging tree behind.
    # The age guard spares a tree another process is still cloning into
    workspaces_root = ws_lib.workspaces_root()
    if workspaces_root.is_dir():
        cutoff = time.time() - STALE_CLONE_AGE_SEC
        for item in workspaces_root.glob(".clone-*"):
            try:
                if _newest_mtime(item) > cutoff:
                    continue
            except OSError:
                continue
            shutil.rmtree(item, ignore_errors=True)
            cleaned["stale_clone_dirs"] += 1

    return cleaned
