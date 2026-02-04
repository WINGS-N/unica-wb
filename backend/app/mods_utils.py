from pathlib import Path


def parse_unica_mod_entries(unica_root: Path) -> list[dict[str, str | bool]]:
    mods_dir = unica_root / "unica" / "mods"
    if not mods_dir.exists():
        return []

    entries: list[dict[str, str | bool]] = []
    for mod_dir in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not mod_dir.is_dir():
            continue
        module_prop = mod_dir / "module.prop"
        if not module_prop.is_file():
            continue

        name = mod_dir.name
        author = ""
        description = ""
        try:
            for raw in module_prop.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if line.startswith("name="):
                    name = line.split("=", 1)[1].strip() or name
                elif line.startswith("author="):
                    author = line.split("=", 1)[1].strip()
                elif line.startswith("description="):
                    description = line.split("=", 1)[1].strip()
        except Exception:
            pass

        entries.append(
            {
                "id": mod_dir.name,
                "module_dir": mod_dir.name,
                "name": name,
                "author": author,
                "description": description,
                "default_disabled": (mod_dir / "disable").exists(),
            }
        )
    return entries


def apply_mods_disabled_overrides(unica_root: Path, disabled_ids: list[str]) -> dict[str, list[Path | tuple[Path, Path]]] | None:
    mods_dir = unica_root / "unica" / "mods"
    if not mods_dir.exists():
        return None

    disabled_set = {x.strip() for x in (disabled_ids or []) if x and x.strip()}

    created_disable: list[Path] = []
    removed_disable_backups: list[tuple[Path, Path]] = []
    for mod_path in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not mod_path.is_dir():
            continue
        module_prop = mod_path / "module.prop"
        if not module_prop.is_file():
            continue
        mod_id = mod_path.name
        disable_path = mod_path / "disable"
        desired_disabled = mod_id in disabled_set
        if desired_disabled:
            if not disable_path.exists():
                disable_path.write_text("disabled by unica-wb for one build\n", encoding="utf-8")
                created_disable.append(disable_path)
            continue
        if disable_path.exists():
            backup_path = mod_path / ".disable.unica-wb.bak"
            try:
                if backup_path.exists():
                    backup_path.unlink(missing_ok=True)
                disable_path.rename(backup_path)
                removed_disable_backups.append((backup_path, disable_path))
            except Exception:
                pass

    if not created_disable and not removed_disable_backups:
        return None
    return {"created_disable": created_disable, "removed_disable_backups": removed_disable_backups}


def restore_mods_overrides(state: dict | None):
    if not state:
        return
    for disable_path in state.get("created_disable", []):
        try:
            disable_path.unlink(missing_ok=True)
        except Exception:
            pass
    for backup_path, disable_path in state.get("removed_disable_backups", []):
        try:
            if backup_path.exists():
                backup_path.rename(disable_path)
        except Exception:
            pass
