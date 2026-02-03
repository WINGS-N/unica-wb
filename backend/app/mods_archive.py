import json
import tarfile
import uuid
import zipfile
from pathlib import Path
from typing import Any


class ModsArchiveError(Exception):
    pass


def _safe_join(base: Path, rel: str) -> Path:
    out = (base / rel).resolve()
    if not str(out).startswith(str(base.resolve())):
        raise ModsArchiveError(f"Unsafe archive path: {rel}")
    return out


def _extract_zip(archive: Path, dest: Path):
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name or name.endswith('/'):
                continue
            target = _safe_join(dest, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, 'r') as src, target.open('wb') as dst:
                dst.write(src.read())


def _extract_tar(archive: Path, dest: Path):
    with tarfile.open(archive, mode='r:*') as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            target = _safe_join(dest, member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            f = tf.extractfile(member)
            if f is None:
                continue
            with f, target.open('wb') as dst:
                dst.write(f.read())


def extract_archive(archive: Path, dest: Path):
    if zipfile.is_zipfile(archive):
        _extract_zip(archive, dest)
        return
    try:
        _extract_tar(archive, dest)
    except tarfile.ReadError as exc:
        raise ModsArchiveError('Unsupported archive format') from exc


def _find_modules_root(extract_dir: Path) -> tuple[Path, list[Path]]:
    direct = [d for d in extract_dir.iterdir() if d.is_dir() and (d / 'module.prop').is_file()]
    if direct:
        return extract_dir, sorted(direct, key=lambda x: x.name)

    top_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
    if len(top_dirs) == 1:
        root = top_dirs[0]
        nested = [d for d in root.iterdir() if d.is_dir() and (d / 'module.prop').is_file()]
        if nested:
            return root, sorted(nested, key=lambda x: x.name)

    raise ModsArchiveError('Archive must contain modules with structure module-name/module.prop')


def parse_module_prop(module_prop: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    for raw in module_prop.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        props[k.strip()] = v.strip()
    return props


def validate_mods_archive(archive: Path, work_dir: Path) -> dict[str, Any]:
    extract_dir = work_dir / 'extract'
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_archive(archive, extract_dir)
    modules_root, module_dirs = _find_modules_root(extract_dir)

    modules: list[dict[str, Any]] = []
    for module_dir in module_dirs:
        props = parse_module_prop(module_dir / 'module.prop')
        modules.append(
            {
                'module_dir': module_dir.name,
                'id': props.get('id', ''),
                'name': props.get('name', module_dir.name),
                'version': props.get('version', ''),
                'versionCode': props.get('versionCode', ''),
                'author': props.get('author', ''),
                'description': props.get('description', ''),
                'props': props,
            }
        )

    if not modules:
        raise ModsArchiveError('No valid modules found in archive')

    return {
        'modules_root': str(modules_root),
        'modules': modules,
    }


def uploads_dir(data_dir: str) -> Path:
    p = Path(data_dir) / 'uploads'
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_upload_id() -> str:
    return uuid.uuid4().hex


def upload_meta_path(data_dir: str, upload_id: str) -> Path:
    return uploads_dir(data_dir) / f'{upload_id}.json'


def upload_archive_path(data_dir: str, upload_id: str, original_name: str) -> Path:
    suffix = ''.join(Path(original_name).suffixes) or '.bin'
    return uploads_dir(data_dir) / f'{upload_id}{suffix}'


def load_upload_meta(data_dir: str, upload_id: str) -> dict[str, Any] | None:
    p = upload_meta_path(data_dir, upload_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def save_upload_meta(data_dir: str, upload_id: str, payload: dict[str, Any]):
    p = upload_meta_path(data_dir, upload_id)
    p.write_text(json.dumps(payload, ensure_ascii=True), encoding='utf-8')
