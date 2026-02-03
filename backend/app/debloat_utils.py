import re
from pathlib import Path


def parse_unica_debloat_entries(unica_root: Path) -> list[dict[str, str]]:
    debloat_file = unica_root / 'unica' / 'debloat.sh'
    if not debloat_file.exists():
        return []

    entries: list[dict[str, str]] = []
    section = 'General'
    in_block = False
    partition = ''

    for raw in debloat_file.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw.rstrip('\n')
        stripped = line.strip()

        if stripped.startswith('#') and len(stripped) > 1:
            title = stripped.lstrip('#').strip()
            if title and not title.startswith('-'):
                section = title
            continue

        if not in_block:
            m = re.match(r'^(ODM|PRODUCT|SYSTEM|SYSTEM_EXT|VENDOR)_DEBLOAT\+="\s*$', stripped)
            if m:
                in_block = True
                partition = m.group(1).lower()
            continue

        # end of multiline debloat block
        if stripped == '"':
            in_block = False
            partition = ''
            continue

        value = stripped
        if not value or value.startswith('#') or '$(' in value:
            continue

        entries.append(
            {
                'id': f'{partition}:{value}',
                'partition': partition,
                'path': value,
                'section': section,
            }
        )

    return entries


def apply_debloat_overrides(
    unica_root: Path,
    disabled_ids: list[str],
    added_system_paths: list[str] | None = None,
    added_product_paths: list[str] | None = None,
) -> tuple[Path, Path] | None:
    added_system_paths = [x.strip() for x in (added_system_paths or []) if x and x.strip()]
    added_product_paths = [x.strip() for x in (added_product_paths or []) if x and x.strip()]

    if not disabled_ids and not added_system_paths and not added_product_paths:
        return None

    target = unica_root / 'unica' / 'debloat.sh'
    if not target.exists():
        return None

    disabled_paths = {x.split(':', 1)[1] for x in disabled_ids if ':' in x}

    backup = unica_root / 'unica' / '.debloat.sh.bak.unica-wb'
    backup.write_bytes(target.read_bytes())

    out_lines = []
    for raw in target.read_text(encoding='utf-8', errors='ignore').splitlines(True):
        stripped = raw.strip()
        if stripped in disabled_paths and not stripped.startswith('#'):
            out_lines.append(f'# UNICA_WB_DISABLED {raw}')
        else:
            out_lines.append(raw)

    if added_system_paths or added_product_paths:
        out_lines.append('\n# UNICA_WB custom debloat entries\n')
        if added_system_paths:
            out_lines.append('SYSTEM_DEBLOAT+="\n')
            for p in added_system_paths:
                out_lines.append(f'{p}\n')
            out_lines.append('"\n')
        if added_product_paths:
            out_lines.append('PRODUCT_DEBLOAT+="\n')
            for p in added_product_paths:
                out_lines.append(f'{p}\n')
            out_lines.append('"\n')

    target.write_text(''.join(out_lines), encoding='utf-8')
    return target, backup


def restore_debloat_file(patched: Path, backup: Path):
    if patched.exists() and backup.exists():
        patched.write_bytes(backup.read_bytes())
        backup.unlink(missing_ok=True)
