import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import asc
from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting, BuildJob, Workspace

logger = logging.getLogger(__name__)

# Sub-directories of workspaces_root that can never be a workspace slug
RESERVED_SLUGS = {"out", "odin", "fw", "tools", "lost+found"}

_SLUG_STRIP = re.compile(r"[^a-z0-9._-]+")
_SLUG_TRIM = re.compile(r"^[._-]+|[._-]+$")


class WorkspaceError(RuntimeError):
    pass


def slugify(value: str) -> str:
    raw = _SLUG_STRIP.sub("-", (value or "").strip().lower())
    raw = _SLUG_TRIM.sub("", raw)
    return raw[:64]


def workspaces_root() -> Path:
    return Path(settings.workspaces_root or "/workspace")


def shared_cache_root() -> Path:
    return workspaces_root() / (settings.shared_cache_dirname or "_shared")


def is_reserved_slug(slug: str) -> bool:
    return slug in RESERVED_SLUGS or slug == (settings.shared_cache_dirname or "_shared")


def root_path(ws: Workspace) -> Path:
    if ws.root_path:
        return Path(ws.root_path)
    return workspaces_root() / ws.slug


def out_path(ws: Workspace) -> Path:
    # buildenv.sh hardcodes OUT_DIR="$SRC_DIR/out", so this is never configurable
    return root_path(ws) / "out"


def logs_dir(ws: Workspace) -> Path:
    return Path(settings.logs_dir) / ws.id


def fw_scope(ws: Workspace) -> str:
    # Progress/cache namespace: workspaces sharing the firmware cache also share
    # the download progress of a given MODEL_CSC
    return "shared" if ws.shared_fw_cache else ws.id


def _move_cache_entries(src: Path, dst: Path):
    # Same-volume rename, so this is instant even for tens of GB. A key that
    # already exists on the destination is a duplicate of the same cache and is
    # dropped rather than merged
    dst.mkdir(parents=True, exist_ok=True)
    for entry in sorted(src.iterdir(), key=lambda x: x.name):
        target = dst / entry.name
        if target.exists():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            continue
        try:
            os.replace(entry, target)
        except OSError:
            # Cross-device: fall back to a copy so nothing is lost
            if entry.is_dir():
                shutil.copytree(entry, target, symlinks=True)
                shutil.rmtree(entry, ignore_errors=True)
            else:
                shutil.copy2(entry, target)
                entry.unlink(missing_ok=True)


def _link_shared(out_dir: Path, name: str):
    link = out_dir / name
    target = shared_cache_root() / name
    target.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if Path(os.readlink(link)) == target:
            return
        link.unlink()
    elif link.is_dir():
        _move_cache_entries(link, target)
        shutil.rmtree(link, ignore_errors=True)
    elif link.exists():
        link.unlink(missing_ok=True)
    link.symlink_to(target, target_is_directory=True)


def _unlink_shared(out_dir: Path, name: str):
    link = out_dir / name
    if link.is_symlink():
        link.unlink()
    link.mkdir(parents=True, exist_ok=True)


def ensure_layout(ws: Workspace):
    # Idempotent: creates the workspace tree and (un)wires the shared firmware
    # cache symlinks to match shared_fw_cache. Safe to call on every request
    root = root_path(ws)
    out = out_path(ws)
    try:
        root.mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
        for name in ("odin", "fw"):
            if ws.shared_fw_cache:
                _link_shared(out, name)
            else:
                _unlink_shared(out, name)
    except OSError as exc:
        logger.warning("workspace layout for %s failed: %s", ws.slug, exc)


@dataclass(frozen=True)
class WorkspaceRef:
    # Detached snapshot of a workspace row: safe to hand to worker threads and to
    # background tasks that must not hold on to a Session
    id: str
    slug: str
    name: str
    root: Path
    out: Path
    logs: Path
    fw_scope: str
    shared_fw_cache: bool
    git_url: str
    git_ref: str
    git_username: str
    git_token: str
    source_config_override: str
    targets_override: str


def snapshot(ws: Workspace) -> WorkspaceRef:
    return WorkspaceRef(
        id=ws.id,
        slug=ws.slug,
        name=ws.name,
        root=root_path(ws),
        out=out_path(ws),
        logs=logs_dir(ws),
        fw_scope=fw_scope(ws),
        shared_fw_cache=bool(ws.shared_fw_cache),
        git_url=ws.git_url or "",
        git_ref=ws.git_ref or settings.repo_ref_default,
        git_username=ws.git_username or "",
        git_token=ws.git_token or "",
        source_config_override=(ws.source_config_override or "").strip(),
        targets_override=(ws.targets_override or "").strip(),
    )


def list_workspaces(db: Session) -> list[Workspace]:
    return db.query(Workspace).order_by(asc(Workspace.position), asc(Workspace.created_at)).all()


def default_workspace(db: Session) -> Workspace | None:
    return db.query(Workspace).order_by(asc(Workspace.position), asc(Workspace.created_at)).first()


def get_workspace(db: Session, workspace_id: str | None) -> Workspace | None:
    if workspace_id:
        ws = db.get(Workspace, workspace_id)
        if ws:
            return ws
    return default_workspace(db)


def require_workspace(db: Session, workspace_id: str | None) -> Workspace:
    ws = get_workspace(db, workspace_id)
    if not ws:
        raise WorkspaceError("No workspace configured")
    return ws


def unique_slug(db: Session, base: str) -> str:
    candidate = slugify(base) or "workspace"
    if is_reserved_slug(candidate):
        candidate = f"{candidate}-ws"
    suffix = 1
    slug = candidate
    while db.query(Workspace).filter(Workspace.slug == slug).first() is not None:
        suffix += 1
        slug = f"{candidate}-{suffix}"
    return slug


def create_workspace(
    db: Session,
    *,
    name: str,
    git_url: str,
    git_ref: str,
    git_username: str = "",
    git_token: str = "",
    shared_fw_cache: bool = True,
    slug: str | None = None,
) -> Workspace:
    display = (name or "").strip() or "Workspace"
    resolved_slug = unique_slug(db, slug or display)
    position = (db.query(Workspace).count() or 0) + 1
    ws = Workspace(
        name=display,
        slug=resolved_slug,
        git_url=(git_url or "").strip(),
        git_ref=(git_ref or "").strip() or settings.repo_ref_default,
        git_username=(git_username or "").strip(),
        git_token=(git_token or "").strip(),
        shared_fw_cache=bool(shared_fw_cache),
        position=position,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    ensure_layout(ws)
    return ws


def serialize(ws: Workspace) -> dict:
    root = root_path(ws)
    return {
        "id": ws.id,
        "name": ws.name,
        "slug": ws.slug,
        "root_path": str(root),
        "out_path": str(out_path(ws)),
        "repo_exists": (root / ".git").is_dir(),
        "git_url": ws.git_url,
        "git_ref": ws.git_ref,
        "git_username": ws.git_username,
        "git_token_set": bool(ws.git_token),
        "shared_fw_cache": bool(ws.shared_fw_cache),
        "fw_scope": fw_scope(ws),
        "source_config_override": ws.source_config_override or "",
        "targets_override": ws.targets_override or "",
        "position": ws.position,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


def bootstrap(db: Session):
    # First boot after the multi-workspace upgrade: adopt the legacy single-repo
    # layout as workspace #1 so nothing has to be re-cloned or re-downloaded
    if db.query(Workspace).count() > 0:
        return

    legacy_root = Path(settings.un1ca_root)
    name = legacy_root.name or "UN1CA"
    ws = Workspace(
        name=name,
        slug=unique_slug(db, name),
        # The legacy tree keeps its own out/, sharing can be enabled from the UI
        root_path=str(legacy_root),
        git_url=_legacy_setting(db, "repo.git_url", settings.repo_url_default),
        git_ref=_legacy_setting(db, "repo.git_ref", settings.repo_ref_default),
        git_username=_legacy_setting(db, "repo.git_username", ""),
        git_token=_legacy_setting(db, "repo.git_token", ""),
        shared_fw_cache=False,
        source_config_override=_legacy_setting(db, "source_config_override", ""),
        targets_override=_legacy_setting(db, "targets_override", ""),
        position=1,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    db.query(BuildJob).filter(BuildJob.workspace_id.is_(None)).update({BuildJob.workspace_id: ws.id})
    db.commit()
    ensure_layout(ws)
    logger.info("bootstrapped default workspace %s at %s", ws.slug, root_path(ws))


def _legacy_setting(db: Session, key: str, default: str) -> str:
    row = db.get(AppSetting, key)
    if row and row.value:
        return row.value.strip()
    return default
