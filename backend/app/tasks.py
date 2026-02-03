import glob
import json
import os
import errno
import re
import signal
import shutil
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .database import SessionLocal
from .debloat_utils import apply_debloat_overrides, restore_debloat_file
from .firmware_progress import set_progress
from .repo_progress import clear_progress as clear_repo_progress, set_progress as set_repo_progress
from .mods_archive import validate_mods_archive
from .models import BuildJob
from .queue import redis_conn
from rq.exceptions import NoSuchJobError
from rq.job import Job


def _now():
    return datetime.now(timezone.utc)


def _safe_target(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in ("_", "-"))


def _firmware_key_from_value(value: str | None) -> str:
    # Из MODEL/CSC/... делаем ключ MODEL_CSC, единый id для прогресса и cache card.
    parts = (value or "").split("/")
    if len(parts) < 2:
        return ""
    model = parts[0].strip().upper()
    csc = parts[1].strip().upper()
    if not model or not csc:
        return ""
    return f"{model}_{csc}"


def _to_bytes(number: float, unit: str) -> int:
    # Нормализуем KiB/MiB/GiB и классические KB/MB в bytes.
    normalized = (unit or "").strip().upper().replace("IB", "B")
    scale = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }.get(normalized, 1)
    return int(number * scale)


_RE_CACHE_KEY = re.compile(r"(SM-[A-Z0-9]+_[A-Z0-9]+)", re.IGNORECASE)
_RE_MODEL_CSC = re.compile(r"(SM-[A-Z0-9]+)[/_]([A-Z0-9]{2,4})", re.IGNORECASE)
_RE_PERCENT = re.compile(r"(?P<pct>\d{1,3})%")
_RE_BYTES = re.compile(
    r"(?P<done>\d+(?:\.\d+)?)\s*(?P<du>[KMGTP]?i?B)\s*/\s*(?P<total>\d+(?:\.\d+)?)\s*(?P<tu>[KMGTP]?i?B)",
    re.IGNORECASE,
)
_RE_SPEED = re.compile(r"(?P<spd>\d+(?:\.\d+)?)\s*(?P<su>[KMGTP]?i?B)/s", re.IGNORECASE)
_RE_ELAPSED_ETA = re.compile(r"\[(?P<elapsed>\d{1,2}:\d{2}(?::\d{2})?)<(?P<eta>\d{1,2}:\d{2}(?::\d{2})?)")
_RE_GIT_PERCENT = re.compile(r"(\d{1,3})%")
_RE_GIT_SPEED = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGTP]?i?B/s)", re.IGNORECASE)


def _guess_fw_key(text: str, known_keys: list[str]) -> str:
    # Пытаемся вытащить fw_key из текущей строки лога, чтобы progress привязать к правильной карточке.
    if not text:
        return ""
    match = _RE_CACHE_KEY.search(text)
    if match:
        return match.group(1).upper()
    match = _RE_MODEL_CSC.search(text)
    if match:
        return f"{match.group(1).upper()}_{match.group(2).upper()}"
    for key in known_keys:
        if key and key in text.upper():
            return key
    return ""


def _parse_progress(text: str) -> dict | None:
    # Парсим tqdm-like output: percent, done/total bytes, speed, elapsed, eta.
    if not text:
        return None
    pct_match = _RE_PERCENT.search(text)
    bytes_match = _RE_BYTES.search(text)
    if not pct_match and not bytes_match:
        return None
    payload: dict[str, int] = {}
    percent = None
    if pct_match:
        percent = max(0, min(100, int(pct_match.group("pct"))))
        payload["percent"] = percent
    if bytes_match:
        done_val = float(bytes_match.group("done"))
        total_val = float(bytes_match.group("total"))
        done_bytes = _to_bytes(done_val, bytes_match.group("du"))
        total_bytes = _to_bytes(total_val, bytes_match.group("tu"))
        payload["downloaded_bytes"] = done_bytes
        payload["total_bytes"] = total_bytes
        if percent is None and total_bytes > 0:
            payload["percent"] = max(0, min(100, int((done_bytes / total_bytes) * 100)))
    speed_match = _RE_SPEED.search(text)
    if speed_match:
        speed_val = float(speed_match.group("spd"))
        payload["speed_bps"] = _to_bytes(speed_val, speed_match.group("su"))
    times_match = _RE_ELAPSED_ETA.search(text)
    if times_match:
        payload["elapsed_sec"] = _parse_hms(times_match.group("elapsed"))
        payload["eta_sec"] = _parse_hms(times_match.group("eta"))
    return payload or None


def _parse_hms(value: str) -> int:
    parts = [int(x) for x in (value or "").split(":") if x.isdigit()]
    if len(parts) == 2:
        mm, ss = parts
        return mm * 60 + ss
    if len(parts) == 3:
        hh, mm, ss = parts
        return hh * 3600 + mm * 60 + ss
    return 0


def _repo_set_progress(payload: dict):
    set_repo_progress({"scope": "repo", **payload})


def _repo_root_dir() -> Path:
    base = Path(settings.un1ca_root)
    nested = base / "UN1CA"
    if (base / ".git").is_dir() or (base / "target").is_dir():
        return base
    if (nested / ".git").is_dir() or (nested / "target").is_dir():
        return nested
    return base


def _repo_progress_from_line(line: str, started_at: float) -> dict:
    pct = None
    m_pct = _RE_GIT_PERCENT.search(line or "")
    if m_pct:
        try:
            pct = max(0, min(100, int(m_pct.group(1))))
        except Exception:
            pct = None

    speed_bps = None
    m_speed = _RE_GIT_SPEED.search(line or "")
    if m_speed:
        try:
            speed_bps = _to_bytes(float(m_speed.group(1)), m_speed.group(2).replace("/s", ""))
        except Exception:
            speed_bps = None

    elapsed = max(0, int(time.time() - started_at))
    eta = None
    if pct and pct > 0 and pct < 100:
        eta = int((elapsed * (100 - pct)) / pct)

    out = {"elapsed_sec": elapsed}
    if pct is not None:
        out["percent"] = pct
    if speed_bps is not None:
        out["speed_bps"] = speed_bps
    if eta is not None:
        out["eta_sec"] = max(0, eta)
    return out


def _stream_command_with_progress(
    command: list[str],
    *,
    log_file: Path,
    env: dict,
    stage: str,
    title: str,
    on_started=None,
) -> int:
    started_at = time.time()
    _repo_set_progress({"type": "progress", "status": "running", "stage": stage, "title": title, "percent": 0, "elapsed_sec": 0})
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=0,
    )
    if on_started:
        on_started(proc.pid)
    assert proc.stdout
    with log_file.open("ab") as lf:
        while True:
            chunk = proc.stdout.read(4096)
            if chunk == "":
                break
            lf.write(chunk.encode("utf-8", errors="ignore"))
            lf.flush()
            for line in re.split(r"[\r\n]+", chunk):
                text = line.strip()
                if not text:
                    continue
                payload = _repo_progress_from_line(text, started_at)
                _repo_set_progress(
                    {
                        "type": "progress",
                        "status": "running",
                        "stage": stage,
                        "title": title,
                        "message": text,
                        **payload,
                    }
                )
    rc = proc.wait()
    if on_started:
        on_started(None)
    return rc


class _FirmwareProgressTracker:
    # Трекер публикует progress в Redis для WS UI, включая heartbeat если лог молчит.
    def __init__(self, job_id: str, known_keys: list[str], phase: str = "download"):
        self.job_id = job_id
        self.known_keys = [x for x in known_keys if x]
        self.current_key = self.known_keys[0] if len(self.known_keys) == 1 else ""
        self.started_keys: set[str] = set()
        self._last_emit: dict[str, tuple[int, float]] = {}
        self._started_at: dict[str, float] = {}
        self.phase = phase

    def feed(self, text: str):
        # Кормим сырыми чанками stdout/stderr; внутри сами режем по \r и \n.
        for part in re.split(r"[\r\n]+", text):
            line = part.strip()
            if not line:
                continue
            guessed = _guess_fw_key(line, self.known_keys)
            if guessed:
                self.current_key = guessed
            progress = _parse_progress(line)
            key = self.current_key or (self.known_keys[0] if len(self.known_keys) == 1 else "")
            if not progress or not key:
                continue
            pct = int(progress.get("percent", -1))
            now = time.time()
            last_pct, last_ts = self._last_emit.get(key, (-1, 0.0))
            if pct >= 0 and pct == last_pct and (now - last_ts) < 0.9:
                continue
            self._last_emit[key] = (pct, now)
            self.started_keys.add(key)
            self._started_at.setdefault(key, time.time())
            effective_elapsed = int(time.time() - self._started_at[key])
            set_progress(
                key,
                {
                    "type": "progress",
                    "status": "running",
                    "phase": self.phase,
                    "job_id": self.job_id,
                    "elapsed_sec": progress.get("elapsed_sec", effective_elapsed),
                    **progress,
                },
            )

    def heartbeat(self):
        # Heartbeat keeps UI alive, useful когда extract не печатает процент.
        targets = self.started_keys or set(self.known_keys)
        now = time.time()
        for key in targets:
            self._started_at.setdefault(key, now)
            last_pct = self._last_emit.get(key, (0, 0.0))[0]
            set_progress(
                key,
                {
                    "type": "progress",
                    "status": "running",
                    "phase": self.phase,
                    "job_id": self.job_id,
                    "percent": max(0, last_pct),
                    "elapsed_sec": int(now - self._started_at[key]),
                },
            )

    def finalize(self, ok: bool):
        # Финализируем состояние progress как completed/failed.
        targets = sorted(self.started_keys or set(self.known_keys))
        if not targets:
            return
        for key in targets:
            set_progress(
                key,
                {
                    "type": "progress",
                    "status": "completed" if ok else "failed",
                    "phase": self.phase,
                    "job_id": self.job_id,
                    "percent": 100 if ok else self._last_emit.get(key, (0, 0.0))[0],
                },
            )


def run_extract_samsung_fw(fw_key: str, target_codename: str):
    model, csc = ("", "")
    if "_" in fw_key:
        model, csc = fw_key.split("_", 1)
    if not model or not csc:
        raise ValueError("Invalid fw key")

    firmware = f"{model}/{csc}/350000000000000"
    cmd = (
        f"cd {shlex.quote(settings.un1ca_root)} && "
        f"source buildenv.sh {shlex.quote(target_codename)} && "
        f"scripts/extract_fw.sh --ignore-source --ignore-target --force {shlex.quote(firmware)}"
    )

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    subprocess.check_call(["bash", "-lc", cmd], env=env)


def _run_operation_job(job_id: str, operation):
    # Общая обертка operation jobs: status lifecycle + log_path + error handling.
    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return
        Path(settings.logs_dir).mkdir(parents=True, exist_ok=True)
        op_name = _safe_target(job.operation_name or "operation")
        log_file = Path(settings.logs_dir) / f"{op_name}-{job.id}.log"
        job.status = "running"
        job.started_at = _now()
        job.log_path = str(log_file)
        db.commit()
        operation(log_file)
        job = db.get(BuildJob, job_id)
        if job:
            job.status = "succeeded"
            job.return_code = 0
            job.finished_at = _now()
            db.commit()
    except Exception as exc:  # noqa: BLE001
        job = db.get(BuildJob, job_id)
        if job:
            if job.status != "canceled":
                job.status = "failed"
                job.error = str(exc)
                job.return_code = 1
                job.finished_at = _now()
                db.commit()
    finally:
        db.close()


def _set_job_pid(job_id: str, pid: int | None):
    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return
        job.process_pid = pid
        db.commit()
    finally:
        db.close()


def run_extract_samsung_fw_job(job_id: str, fw_key: str, target_codename: str):
    # Extract FW from ODIN cache into out/fw, always with --force for consistent result.
    def _op(log_file: Path):
        cmd = (
            f"cd {shlex.quote(settings.un1ca_root)} && "
            f"source buildenv.sh {shlex.quote(target_codename)} && "
            f"scripts/extract_fw.sh --ignore-source --ignore-target --force "
            f"{shlex.quote(fw_key.replace('_', '/', 1) + '/350000000000000')}"
        )
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        tracker = _FirmwareProgressTracker(job_id, [fw_key.upper()], phase="extract")
        tracker.heartbeat()
        with log_file.open("ab") as lf:
            lf.write(f"[extract] fw_key={fw_key} target={target_codename}\n".encode("utf-8"))
            lf.flush()
            proc = subprocess.Popen(
                ["bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=0,
            )
            db = SessionLocal()
            try:
                job = db.get(BuildJob, job_id)
                if job:
                    job.process_pid = proc.pid
                    db.commit()
            finally:
                db.close()
            assert proc.stdout
            ok = False
            try:
                last_heartbeat = 0.0
                while True:
                    chunk = proc.stdout.read(4096)
                    if chunk == "":
                        break
                    lf.write(chunk.encode("utf-8", errors="ignore"))
                    lf.flush()
                    tracker.feed(chunk)
                    now = time.time()
                    if now - last_heartbeat >= 1.0:
                        tracker.heartbeat()
                        last_heartbeat = now
                rc = proc.wait()
                if rc != 0:
                    raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
                ok = True
            finally:
                db = SessionLocal()
                try:
                    job = db.get(BuildJob, job_id)
                    if job:
                        job.process_pid = None
                        db.commit()
                finally:
                    db.close()
                tracker.finalize(ok)

    _run_operation_job(job_id, _op)


def run_delete_samsung_fw_job(job_id: str, fw_type: str, fw_key: str):
    # Delete cached Odin/FW entry from out tree.
    def _delete(log_file: Path):
        base = Path(settings.out_dir) / ("odin" if fw_type == "odin" else "fw")
        target = base / fw_key
        with log_file.open("ab") as lf:
            lf.write(f"[delete] fw_type={fw_type} fw_key={fw_key}\n".encode("utf-8"))
            lf.flush()
        if not target.exists():
            with log_file.open("ab") as lf:
                lf.write(b"[delete] path does not exist, nothing to do\n")
            return
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            with log_file.open("ab") as lf:
                lf.write(f"[delete] removed directory: {target}\n".encode("utf-8"))
        else:
            target.unlink(missing_ok=True)
            with log_file.open("ab") as lf:
                lf.write(f"[delete] removed file: {target}\n".encode("utf-8"))

    _run_operation_job(job_id, _delete)


def run_repo_clone_job(job_id: str, git_url: str, git_ref: str):
    # Clone/update repo with recurse-submodules, same behavior as old init repo-sync.
    def _op(log_file: Path):
        root = _repo_root_dir()
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        root.mkdir(parents=True, exist_ok=True)
        repo_dir = root
        clear_repo_progress()

        db = SessionLocal()
        try:
            job = db.get(BuildJob, job_id)
            if job:
                job.process_pid = None
                db.commit()
        finally:
            db.close()

        keep_out_src = repo_dir / "out"
        keep_out_tmp = Path(settings.data_dir) / "tmp-repo-ops" / f"{job_id}-out"
        if keep_out_src.exists():
            keep_out_tmp.parent.mkdir(parents=True, exist_ok=True)
            if keep_out_tmp.exists():
                shutil.rmtree(keep_out_tmp, ignore_errors=True)
            shutil.move(str(keep_out_src), str(keep_out_tmp))

        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)
        repo_dir.mkdir(parents=True, exist_ok=True)

        rc = _stream_command_with_progress(
            ["git", "clone", "--progress", "--recurse-submodules", git_url, str(repo_dir)],
            log_file=log_file,
            env=env,
            stage="clone",
            title=f"Clone {git_url}",
            on_started=lambda pid: _set_job_pid(job_id, pid),
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, ["git", "clone"])

        setup_cmd = (
            f"cd {shlex.quote(str(repo_dir))} && "
            "git -c safe.directory=* fetch --all --tags --prune && "
            f"git -c safe.directory=* fetch origin {shlex.quote(git_ref)} --prune || true && "
            f"git -c safe.directory=* checkout -f {shlex.quote(git_ref)} && "
            f"if git -c safe.directory=* rev-parse --verify origin/{shlex.quote(git_ref)} >/dev/null 2>&1; then "
            f"git -c safe.directory=* reset --hard origin/{shlex.quote(git_ref)}; fi && "
            "git -c safe.directory=* submodule sync --recursive && "
            "git -c safe.directory=* submodule update --init --recursive --jobs 8"
        )
        rc = _stream_command_with_progress(
            ["bash", "-lc", setup_cmd],
            log_file=log_file,
            env=env,
            stage="submodules",
            title=f"Checkout {git_ref} and sync submodules",
            on_started=lambda pid: _set_job_pid(job_id, pid),
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, ["bash", "-lc", setup_cmd])
        if keep_out_tmp.exists():
            dst_out = repo_dir / "out"
            if dst_out.exists():
                shutil.rmtree(dst_out, ignore_errors=True)
            shutil.move(str(keep_out_tmp), str(dst_out))
        _repo_set_progress({"type": "progress", "status": "completed", "stage": "clone", "title": "Repository clone completed", "percent": 100})

    _run_operation_job(job_id, _op)


def run_repo_pull_job(job_id: str, git_ref: str):
    def _op(log_file: Path):
        root = _repo_root_dir()
        if not (root / ".git").is_dir():
            raise RuntimeError("Repository is not cloned yet")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        clear_repo_progress()
        cmd = (
            f"cd {shlex.quote(str(root))} && "
            "git -c safe.directory=* fetch --all --tags --prune && "
            f"git -c safe.directory=* fetch origin {shlex.quote(git_ref)} --prune || true && "
            f"git -c safe.directory=* checkout -f {shlex.quote(git_ref)} && "
            f"if git -c safe.directory=* rev-parse --verify origin/{shlex.quote(git_ref)} >/dev/null 2>&1; then "
            f"git -c safe.directory=* reset --hard origin/{shlex.quote(git_ref)}; fi"
        )
        rc = _stream_command_with_progress(
            ["bash", "-lc", cmd],
            log_file=log_file,
            env=env,
            stage="pull",
            title=f"Update repository ({git_ref})",
            on_started=lambda pid: _set_job_pid(job_id, pid),
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
        _repo_set_progress({"type": "progress", "status": "completed", "stage": "pull", "title": "Repository updated", "percent": 100})

    _run_operation_job(job_id, _op)


def run_repo_submodules_job(job_id: str):
    def _op(log_file: Path):
        root = _repo_root_dir()
        if not (root / ".git").is_dir():
            raise RuntimeError("Repository is not cloned yet")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        clear_repo_progress()
        cmd = (
            f"cd {shlex.quote(str(root))} && "
            "git -c safe.directory=* submodule sync --recursive && "
            "git -c safe.directory=* submodule update --init --recursive --jobs 8"
        )
        rc = _stream_command_with_progress(
            ["bash", "-lc", cmd],
            log_file=log_file,
            env=env,
            stage="submodules",
            title="Update submodules",
            on_started=lambda pid: _set_job_pid(job_id, pid),
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
        _repo_set_progress({"type": "progress", "status": "completed", "stage": "submodules", "title": "Submodules updated", "percent": 100})

    _run_operation_job(job_id, _op)


def run_repo_delete_job(job_id: str, mode: str = "repo_only"):
    def _op(log_file: Path):
        root = _repo_root_dir()
        clear_repo_progress()
        with log_file.open("ab") as lf:
            lf.write(f"[repo-delete] mode={mode} path={root}\n".encode("utf-8"))
            lf.flush()
        if root.exists():
            if mode == "repo_with_out":
                shutil.rmtree(root, ignore_errors=True)
                root.mkdir(parents=True, exist_ok=True)
            else:
                for item in root.iterdir():
                    if item.name == "out":
                        continue
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
        title = "Repository removed with out" if mode == "repo_with_out" else "Repository removed, out preserved"
        _repo_set_progress({"type": "progress", "status": "completed", "stage": "delete", "title": title, "percent": 100})

    _run_operation_job(job_id, _op)


def run_stop_job_task(job_id: str, signal_type: str = "sigterm"):
    # Worker-side stop: only worker can safely signal build process group.
    def _is_alive(pid: int) -> bool:
        # Проверяем process group first, потому что build запускается в отдельной pgid.
        try:
            os.killpg(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return False
            if exc.errno == errno.EPERM:
                return True
        # Fallback: check process directly.
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH

    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return
        if job.status in {"succeeded", "failed", "reused", "canceled"}:
            return

        if job.status == "queued" and job.queue_job_id:
            try:
                rq_job = Job.fetch(job.queue_job_id, connection=redis_conn)
                rq_job.cancel()
            except NoSuchJobError:
                pass
            except Exception:
                pass
            job.status = "canceled"
            job.error = "Build canceled by user (queued job)"
            job.finished_at = _now()
            db.commit()
            return

        if job.status == "running" and job.process_pid:
            sig = signal.SIGKILL if signal_type == "sigkill" else signal.SIGTERM
            try:
                os.killpg(job.process_pid, sig)
            except Exception:
                try:
                    os.kill(job.process_pid, sig)
                except Exception:
                    pass

            # Confirm termination before marking canceled. If still alive, keep running so user can retry stop.
            timeout_sec = 5 if signal_type == "sigkill" else 25
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                if not _is_alive(job.process_pid):
                    break
                time.sleep(0.5)

            if not _is_alive(job.process_pid):
                job.status = "canceled"
                job.error = "Build canceled by user (SIGKILL)" if signal_type == "sigkill" else "Build canceled by user (SIGTERM)"
                job.finished_at = _now()
                job.process_pid = None
            else:
                job.error = (
                    "Stop requested by user "
                    f"({signal_type.upper()}), but process is still running. Retry stop if needed."
                )
            db.commit()
            return
        if job.status == "running" and not job.process_pid:
            job.error = (
                "Stop requested by user, but build PID is missing. "
                "Please retry stop or check worker logs."
            )
            db.commit()
            return
    finally:
        db.close()


def run_build_job(job_id: str):
    # Основная build pipeline: overrides, extra mods, debloat patching, make_rom, artifact detect.
    db = SessionLocal()
    extra_mods_tmp_dir = None
    applied_mod_dirs: list[Path] = []
    debloat_override_paths: tuple[Path, Path] | None = None
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return

        Path(settings.logs_dir).mkdir(parents=True, exist_ok=True)
        log_file = Path(settings.logs_dir) / f"{_safe_target(job.target)}-{job.id}.log"

        job.status = "running"
        job.started_at = _now()
        job.log_path = str(log_file)
        db.commit()

        flags = []
        if job.force:
            flags.append("--force")
        if job.no_rom_zip:
            flags.append("--no-rom-zip")

        short_commit = (job.source_commit or "unknown")[:8]
        version_suffix = (job.version_suffix or "").strip()
        rom_version = f"{job.version_major}.{job.version_minor}.{job.version_patch}-{short_commit}"
        if version_suffix:
            rom_version += f"-{version_suffix}"

        override_exports = []
        if job.source_firmware:
            override_exports.append(f"export SOURCE_FIRMWARE={shlex.quote(job.source_firmware)}")
        if job.target_firmware:
            override_exports.append(f"export TARGET_FIRMWARE={shlex.quote(job.target_firmware)}")
        if job.version_major is not None and job.version_minor is not None and job.version_patch is not None:
            override_exports.append(f"export ROM_VERSION={shlex.quote(rom_version)}")

        if job.extra_mods_archive_path and Path(job.extra_mods_archive_path).exists():
            # Загруженные extra mods копируем как временные .uploaded-* директории только на время этой сборки.
            extra_mods_tmp_dir = Path(settings.data_dir) / "tmp-extra-mods" / job.id
            extra_mods_tmp_dir.mkdir(parents=True, exist_ok=True)
            validated = validate_mods_archive(Path(job.extra_mods_archive_path), extra_mods_tmp_dir)
            modules_root = Path(validated["modules_root"])
            target_mods_dir = Path(settings.un1ca_root) / "unica" / "mods"
            target_mods_dir.mkdir(parents=True, exist_ok=True)
            for module_dir in sorted(modules_root.iterdir(), key=lambda x: x.name):
                if not module_dir.is_dir() or not (module_dir / "module.prop").is_file():
                    continue
                dst = target_mods_dir / f".uploaded-{job.id[:8]}-{module_dir.name}"
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(module_dir, dst, symlinks=True)
                applied_mod_dirs.append(dst)
            if "--force" not in flags:
                flags.append("--force")
        if job.debloat_disabled_json or job.debloat_add_system_json or job.debloat_add_product_json:
            # Debloat overrides тоже временные: patch before build, restore in finally.
            try:
                disabled_ids = json.loads(job.debloat_disabled_json or "[]")
                add_system = json.loads(job.debloat_add_system_json or "[]")
                add_product = json.loads(job.debloat_add_product_json or "[]")
                if isinstance(disabled_ids, list) and isinstance(add_system, list) and isinstance(add_product, list):
                    debloat_override_paths = apply_debloat_overrides(
                        Path(settings.un1ca_root),
                        disabled_ids,
                        add_system,
                        add_product,
                    )
                if debloat_override_paths:
                    if "--force" not in flags:
                        flags.append("--force")
            except Exception:
                pass

        cmd = f"cd {shlex.quote(settings.un1ca_root)} && source buildenv.sh {shlex.quote(job.target)} && "
        if override_exports:
            cmd += " && ".join(override_exports) + " && "
        cmd += f"scripts/make_rom.sh {' '.join(shlex.quote(x) for x in flags)}"

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        tracker = _FirmwareProgressTracker(
            job.id,
            [
                _firmware_key_from_value(job.source_firmware),
                _firmware_key_from_value(job.target_firmware),
            ],
            phase="download",
        )

        with log_file.open("ab") as lf:
            proc = subprocess.Popen(
                ["bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=0,
                preexec_fn=os.setsid,
            )
            job.process_pid = proc.pid
            db.commit()

            assert proc.stdout
            ok = False
            try:
                last_heartbeat = 0.0
                while True:
                    chunk = proc.stdout.read(4096)
                    if chunk == "":
                        break
                    lf.write(chunk.encode("utf-8", errors="ignore"))
                    lf.flush()
                    tracker.feed(chunk)
                    now = time.time()
                    if now - last_heartbeat >= 1.0:
                        tracker.heartbeat()
                        last_heartbeat = now
                rc = proc.wait()
                ok = rc == 0
            finally:
                tracker.finalize(ok)

        refreshed = db.get(BuildJob, job_id)
        if refreshed:
            refreshed.process_pid = None
            db.commit()

        job.return_code = rc
        job.finished_at = _now()
        if job.status == "canceled":
            job.error = job.error or "Build canceled by user"
        elif rc == 0:
            job.status = "succeeded"
            pattern = str(Path(settings.out_dir) / "UN1CA_*.zip")
            matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
            if matches:
                job.artifact_path = matches[0]
        else:
            job.status = "failed"
            job.error = f"Build failed with return code {rc}"
        db.commit()

    except Exception as exc:  # noqa: BLE001
        job = db.get(BuildJob, job_id)
        if job:
            if job.status != "canceled":
                job.status = "failed"
                job.error = str(exc)
            job.finished_at = _now()
            job.process_pid = None
            db.commit()
    finally:
        for mod_dir in applied_mod_dirs:
            if mod_dir.exists():
                shutil.rmtree(mod_dir, ignore_errors=True)
        if extra_mods_tmp_dir and extra_mods_tmp_dir.exists():
            shutil.rmtree(extra_mods_tmp_dir, ignore_errors=True)
        if debloat_override_paths:
            restore_debloat_file(*debloat_override_paths)
        job = db.get(BuildJob, job_id)
        if job and job.extra_mods_archive_path and Path(job.extra_mods_archive_path).exists():
            try:
                Path(job.extra_mods_archive_path).unlink(missing_ok=True)
            except Exception:
                pass
        db.close()
