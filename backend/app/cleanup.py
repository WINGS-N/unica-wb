import shutil
from pathlib import Path

from . import workspaces as ws_lib
from .config import settings
from .database import SessionLocal


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

    # A worker killed mid-clone leaves a .clone-<job> staging tree behind
    workspaces_root = ws_lib.workspaces_root()
    if workspaces_root.is_dir():
        for item in workspaces_root.glob(".clone-*"):
            shutil.rmtree(item, ignore_errors=True)
            cleaned["stale_clone_dirs"] += 1

    return cleaned
