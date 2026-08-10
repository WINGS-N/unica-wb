import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import settings

# GitHub username rules, enforced so this endpoint cannot be pointed anywhere else
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

# How long a cached avatar is served without asking GitHub. After that the copy
# is revalidated with its ETag, so a changed avatar shows up within the hour
# while an unchanged one costs a 304
FRESH_SEC = 3600.0
TIMEOUT_SEC = 10.0
MIN_SIZE = 32
MAX_SIZE = 460


class AvatarError(Exception):
    pass


def _cache_dir() -> Path:
    return Path(settings.data_dir) / "avatars"


def _paths(username: str, size: int) -> tuple[Path, Path]:
    base = _cache_dir() / f"{username.lower()}-{size}"
    return base.with_suffix(".img"), base.with_suffix(".json")


def _read_meta(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_meta(path: Path, payload: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    except OSError:
        pass


def clamp_size(size: int) -> int:
    return max(MIN_SIZE, min(int(size or 88), MAX_SIZE))


def get_avatar(username: str, size: int) -> tuple[bytes, str]:
    # Returns the image bytes and its content type, from disk when possible and
    # from GitHub otherwise. A stale copy is preferred over an error when the
    # network is unavailable
    if not USERNAME_RE.match(username or ""):
        raise AvatarError("Invalid username")
    size = clamp_size(size)
    img_path, meta_path = _paths(username, size)
    meta = _read_meta(meta_path)
    cached = img_path.read_bytes() if img_path.is_file() else b""
    content_type = str(meta.get("content_type") or "image/png")

    if cached and (time.time() - float(meta.get("fetched_at") or 0.0)) < FRESH_SEC:
        return cached, content_type

    url = f"https://github.com/{username}.png?size={size}"
    headers = {"User-Agent": "unica-wb"}
    etag = str(meta.get("etag") or "")
    if cached and etag:
        headers["If-None-Match"] = etag

    try:
        with urlopen(Request(url, headers=headers), timeout=TIMEOUT_SEC) as resp:
            body = resp.read()
            content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
            new_etag = resp.headers.get("ETag", "")
    except HTTPError as exc:
        if exc.code == 304 and cached:
            meta["fetched_at"] = time.time()
            _write_meta(meta_path, meta)
            return cached, content_type
        if cached:
            return cached, content_type
        raise AvatarError(f"GitHub returned {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        if cached:
            return cached, content_type
        raise AvatarError("Avatar is not reachable") from exc

    if not body:
        if cached:
            return cached, content_type
        raise AvatarError("Empty avatar response")

    try:
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(body)
    except OSError:
        pass
    _write_meta(meta_path, {"etag": new_etag, "content_type": content_type, "fetched_at": time.time()})
    return body, content_type
