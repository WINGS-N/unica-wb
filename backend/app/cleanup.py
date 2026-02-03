from pathlib import Path
import shutil

from .config import settings


def cleanup_stale_build_overrides() -> dict[str, int]:
    cleaned = {
        "uploaded_mod_dirs": 0,
        "tmp_extra_mods_dirs": 0,
    }

    mods_dir = Path(settings.un1ca_root) / "unica" / "mods"
    if mods_dir.is_dir():
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

    return cleaned
