import errno
import glob
import hashlib
import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from . import workspaces as ws_lib
from .build_progress import set_progress as set_build_progress
from .config import settings
from .database import SessionLocal
from .debloat_utils import apply_debloat_overrides, restore_debloat_file
from .ff_utils import apply_ff_overrides, restore_ff_overrides
from .firmware_progress import set_progress
from .job_events import publish as publish_job_event
from .models import BuildJob, Workspace
from .mods_archive import validate_mods_archive
from .mods_utils import apply_mods_disabled_overrides, restore_mods_overrides
from .push import notify_job
from .queue import redis_conn
from .repo_progress import clear_progress as clear_repo_progress
from .repo_progress import set_progress as set_repo_progress


def _now():
    return datetime.now(UTC)


def _safe_target(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in ("_", "-"))


def _firmware_key_from_value(value: str | None) -> str:
    # MODEL/CSC/... collapses into one MODEL_CSC key, the id shared by progress and cache cards
    parts = (value or "").split("/")
    if len(parts) < 2:
        return ""
    model = parts[0].strip().upper()
    csc = parts[1].strip().upper()
    if not model or not csc:
        return ""
    return f"{model}_{csc}"


def _workspace_context(db, job: BuildJob) -> ws_lib.WorkspaceRef:
    ws = None
    if job.workspace_id:
        ws = db.get(Workspace, job.workspace_id)
    if ws is None:
        ws = ws_lib.default_workspace(db)
    if ws is None:
        raise RuntimeError("Job has no workspace")
    ws_lib.ensure_layout(ws)
    return ws_lib.snapshot(ws)


def _ensure_fw_extracted(
    ctx: ws_lib.WorkspaceRef,
    target_codename: str,
    source_firmware: str,
    target_firmware: str,
):
    source_key = _firmware_key_from_value(source_firmware)
    target_key = _firmware_key_from_value(target_firmware)
    if not source_key or not target_key:
        return
    src_marker = ctx.out / "fw" / source_key / ".extracted"
    tgt_marker = ctx.out / "fw" / target_key / ".extracted"
    if src_marker.exists() and tgt_marker.exists():
        return
    cmd = (
        f"cd {shlex.quote(str(ctx.root))} && "
        f"source buildenv.sh {shlex.quote(target_codename)} && "
        f"export SOURCE_FIRMWARE={shlex.quote(source_firmware)} && "
        f"export TARGET_FIRMWARE={shlex.quote(target_firmware)} && "
        f"scripts/extract_fw.sh"
    )
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    subprocess.check_call(["bash", "-lc", cmd], env=env)


def _to_bytes(number: float, unit: str) -> int:
    # Normalize KiB/MiB/GiB and plain KB/MB into bytes
    normalized = (unit or "").strip().upper().replace("IB", "B")
    # A bare K/M/G means the same as KB/MB/GB
    if normalized and not normalized.endswith("B"):
        normalized += "B"
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
# A bare "NN%" appears in version strings and log prose, so a percent only counts
# when it is part of a real progress readout: a tqdm bar, or a line that also
# carries a done/total byte pair or a transfer speed
_RE_TQDM_PERCENT = re.compile(r"(?<![\d.])(?P<pct>\d{1,3})\s*%\s*\|")
_RE_LOOSE_PERCENT = re.compile(r"(?<![\d.])(?P<pct>\d{1,3})\s*%")
# tqdm writes units both ways: 2.86GB and a bare 10.1G, so the B is optional
_BYTE_UNIT = r"(?:[KMGTP]i?B?|B)"
_RE_BYTES = re.compile(
    rf"(?P<done>\d+(?:\.\d+)?)\s*(?P<du>{_BYTE_UNIT})\s*/\s*(?P<total>\d+(?:\.\d+)?)\s*(?P<tu>{_BYTE_UNIT})",
    re.IGNORECASE,
)
# A download with an unknown size prints only what it has done so far
_RE_BYTES_DONE_ONLY = re.compile(
    rf"(?<![\d./])(?P<done>\d+(?:\.\d+)?)\s*(?P<du>{_BYTE_UNIT})\s*\[",
    re.IGNORECASE,
)
_RE_SPEED = re.compile(rf"(?P<spd>\d+(?:\.\d+)?)\s*(?P<su>{_BYTE_UNIT})/s", re.IGNORECASE)
_RE_ELAPSED_ETA = re.compile(r"\[(?P<elapsed>\d{1,2}:\d{2}(?::\d{2})?)<(?P<eta>\d{1,2}:\d{2}(?::\d{2})?)")
_DIR_CACHE_KEY_PREFIX = "un1ca:cache:dir_size:"

# make_rom.sh announces every step with LOG_STEP_IN; those banners are the only
# reliable progress signal a shell build gives us. Percentages are the share of
# wall-clock a full build spends before that step, measured on a cold tree
# Stages during which the firmware card still has something to say
_FIRMWARE_BUILD_STAGES = {"dependencies", "download", "extract"}

_BUILD_STAGE_RULES = [
    # A first run compiles the toolchain before anything else happens, and that
    # is the longest silent stretch of the whole build
    ("dependencies", 3, re.compile(r"^- Building |Building dependencies")),
    ("download", 6, re.compile(r"Downloading required firmwares")),
    ("extract", 16, re.compile(r"Extracting required firmwares")),
    ("workdir", 30, re.compile(r"Creating work dir")),
    ("platform_patches", 38, re.compile(r"Applying platform patches")),
    ("device_patches", 45, re.compile(r"Applying device patches")),
    ("rom_patches", 54, re.compile(r"Applying ROM patches")),
    ("rom_mods", 64, re.compile(r"Applying ROM mods")),
    ("apks", 76, re.compile(r"Building APKs/JARs")),
    ("target_files", 86, re.compile(r"Creating target-files zip")),
    ("zip", 93, re.compile(r"Creating (?:flashable )?zip")),
    ("done", 100, re.compile(r"Build completed")),
]

# git clone reports several 0-100% phases in a row. Mapping each phase onto its
# own slice of the bar is what stops it from jumping back to 0 four times
_GIT_PHASES = [
    ("counting", re.compile(r"Counting objects"), 0, 6),
    ("compressing", re.compile(r"Compressing objects"), 6, 18),
    ("receiving", re.compile(r"Receiving objects"), 18, 78),
    ("resolving", re.compile(r"Resolving deltas"), 78, 92),
    ("updating", re.compile(r"(?:Updating|Checking out) files"), 92, 100),
]
_RE_GIT_PHASE_PERCENT = re.compile(r"(?<![\d.])(\d{1,3})%")
_RE_GIT_SPEED = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGTP]?i?B)/s", re.IGNORECASE)


# Credentials are injected into the git command line, and any text carrying that
# command must never leave this process with them intact: job errors are shown
# in the interface and stored in the database
# The downloader draws two identical unlabeled bars in a row, download then
# decrypt, so the only thing telling them apart is that the second starts over
_RE_EXTRACT_LINE = re.compile(r"^\s*-?\s*Extracting\b", re.IGNORECASE)
_RE_VERIFY_LINE = re.compile(r"^\s*-?\s*Verifying\b", re.IGNORECASE)

# Extraction reports named steps and no numbers at all, so the only honest thing
# to show is which step is running
_RE_EXTRACT_STEP = re.compile(
    r"^\s*-\s*(Extracting|Decompressing|Unsparsing|Converting|Mounting|Copying)\s+(?P<what>.+?)\.*\s*$",
    re.IGNORECASE,
)

_RE_URL_CREDENTIALS = re.compile(r"(?<=://)([^/\s:@]+):([^/\s@]+)@")


# Build scripts colour their output, and those codes are meaningless once the
# text is a progress message rather than a terminal line
_RE_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _RE_ANSI.sub("", str(text))


def _sh_dq(value: str) -> str:
    # Value goes inside a double quoted shell assignment written by sed
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("|", "\\|") + '"'


def _redact(text: str) -> str:
    return _RE_URL_CREDENTIALS.sub(r"\1:***@", str(text))


def _guess_fw_key(text: str, known_keys: list[str]) -> str:
    # Pull the fw_key out of the current log line so progress lands on the right card
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
    # Parse tqdm-like output: percent, done/total bytes, speed, elapsed, eta
    if not text:
        return None
    bytes_match = _RE_BYTES.search(text)
    done_only = None if bytes_match else _RE_BYTES_DONE_ONLY.search(text)
    speed_match = _RE_SPEED.search(text)
    pct_match = _RE_TQDM_PERCENT.search(text)
    if not pct_match and (bytes_match or speed_match):
        pct_match = _RE_LOOSE_PERCENT.search(text)
    if not pct_match and not bytes_match and not done_only:
        return None
    payload: dict[str, int] = {}
    percent = None
    if pct_match:
        percent = max(0, min(100, int(pct_match.group("pct"))))
        payload["percent"] = percent
    if done_only:
        payload["downloaded_bytes"] = _to_bytes(float(done_only.group("done")), done_only.group("du"))
    if bytes_match:
        done_val = float(bytes_match.group("done"))
        total_val = float(bytes_match.group("total"))
        done_bytes = _to_bytes(done_val, bytes_match.group("du"))
        total_bytes = _to_bytes(total_val, bytes_match.group("tu"))
        payload["downloaded_bytes"] = done_bytes
        payload["total_bytes"] = total_bytes
        if percent is None and total_bytes > 0:
            payload["percent"] = max(0, min(100, int((done_bytes / total_bytes) * 100)))
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


def _dir_cache_key_for_path(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
    return f"{_DIR_CACHE_KEY_PREFIX}{digest}"


def _invalidate_dir_size_cache_paths(paths: list[Path]):
    # Event-based invalidation for size cache so UI gets fresh values right after filesystem ops
    keys = []
    seen = set()
    for path in paths:
        p = Path(path)
        variants = [p, p.parent]
        for v in variants:
            key = _dir_cache_key_for_path(v)
            if key in seen:
                continue
            seen.add(key)
            keys.append(key)
    if not keys:
        return
    try:
        redis_conn.delete(*keys)
    except Exception:
        pass


class _GitProgressTracker:
    # Turns git's multi-phase 0-100% chatter into one bar that only moves forward
    def __init__(self, workspace_id: str, stage: str, title: str, base: int = 0, span: int = 100):
        self.workspace_id = workspace_id
        self.stage = stage
        self.title = title
        self.base = base
        self.span = span
        self.started_at = time.time()
        self.percent = base
        self.phase = ""
        self._last_emit = 0.0

    def _map(self, phase_lo: int, phase_hi: int, pct: int) -> int:
        lo = self.base + (phase_lo * self.span) // 100
        hi = self.base + (phase_hi * self.span) // 100
        return lo + ((hi - lo) * max(0, min(100, pct))) // 100

    def emit(self, message: str = "", *, force: bool = False, status: str = "running", extra: dict | None = None):
        now = time.time()
        if not force and (now - self._last_emit) < 0.25:
            return
        self._last_emit = now
        elapsed = max(0, int(now - self.started_at))
        payload = {
            "type": "progress",
            "status": status,
            "stage": self.stage,
            "title": self.title,
            "phase": self.phase,
            "percent": self.percent,
            "indeterminate": self.phase == "",
            "elapsed_sec": elapsed,
        }
        if message:
            payload["message"] = message[:200]
        if extra:
            payload.update(extra)
        set_repo_progress(self.workspace_id, payload)

    def feed_line(self, line: str):
        text = (line or "").strip()
        if not text:
            return
        extra: dict[str, int] = {}
        matched_phase = False
        for name, pattern, lo, hi in _GIT_PHASES:
            if not pattern.search(text):
                continue
            m = _RE_GIT_PHASE_PERCENT.search(text)
            pct = int(m.group(1)) if m else 0
            mapped = self._map(lo, hi, pct)
            if mapped > self.percent:
                self.percent = mapped
            self.phase = name
            matched_phase = True
            break
        speed = _RE_GIT_SPEED.search(text)
        if speed:
            try:
                extra["speed_bps"] = _to_bytes(float(speed.group(1)), speed.group(2))
            except Exception:
                pass
        elapsed = max(1, int(time.time() - self.started_at))
        done = self.percent - self.base
        if done > 0 and done < self.span:
            extra["eta_sec"] = max(0, int(elapsed * (self.span - done) / done))
        self.emit(text, force=matched_phase, extra=extra)

    def finish(self, ok: bool):
        if ok:
            self.percent = self.base + self.span
        self.emit(force=True, status="running" if ok else "failed")


def _stream_command_with_progress(
    command: list[str],
    *,
    log_file: Path,
    env: dict,
    tracker: _GitProgressTracker,
    on_started=None,
) -> int:
    tracker.emit(force=True)
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
    try:
        with log_file.open("ab") as lf:
            while True:
                raw = os.read(proc.stdout.fileno(), 4096)
                if not raw:
                    break
                chunk = raw.decode("utf-8", errors="ignore")
                lf.write(chunk.encode("utf-8", errors="ignore"))
                lf.flush()
                for line in re.split(r"[\r\n]+", chunk):
                    tracker.feed_line(line)
        rc = proc.wait()
    finally:
        if on_started:
            on_started(None)
    tracker.finish(rc == 0)
    return rc


class _WrittenBytesProbe:
    # Extraction prints no numbers, so the only real measure is what lands on
    # disk. Sampling the output tree gives volume and throughput the same way a
    # pipe meter does, without inventing a percentage nobody can compute
    def __init__(self, path: Path):
        self.path = path
        self._at = 0.0
        self._bytes = 0
        self._speed = 0.0
        self._cost = 0.0

    def _measure(self) -> int:
        total = 0
        seen = 0
        for root, _dirs, files in os.walk(self.path, onerror=lambda _e: None):
            for name in files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    continue
                seen += 1
                if seen >= 60000:
                    return total
        return total

    def sample(self) -> tuple[int, int]:
        now = time.monotonic()
        # A walk over a big tree is not free, so the interval grows with the
        # time the previous one took
        interval = max(1.0, min(15.0, self._cost * 20))
        if self._at and now - self._at < interval:
            return self._bytes, int(self._speed)
        started = time.monotonic()
        try:
            total = self._measure()
        except OSError:
            return self._bytes, int(self._speed)
        self._cost = time.monotonic() - started
        if self._at:
            span = now - self._at
            if span > 0 and total >= self._bytes:
                self._speed = (total - self._bytes) / span
        self._at = now
        self._bytes = total
        return self._bytes, int(self._speed)


class _FirmwareProgressTracker:
    # Publishes progress to Redis for the websocket UI, with a heartbeat for silent logs
    def __init__(
        self,
        job_id: str,
        scope: str,
        known_keys: list[str],
        phase: str = "download",
        watch_path: Path | None = None,
    ):
        self.job_id = job_id
        self.scope = scope
        self.known_keys = [x for x in known_keys if x]
        self.current_key = self.known_keys[0] if len(self.known_keys) == 1 else ""
        self.started_keys: set[str] = set()
        self._last_emit: dict[str, tuple[int, float]] = {}
        self._started_at: dict[str, float] = {}
        self.phase = phase
        self.step = ""
        self.probe = _WrittenBytesProbe(watch_path) if watch_path else None
        # Once settled the entry is final: a later heartbeat would put it back
        # into a running state it already left
        self.done = False

    def feed(self, text: str):
        # Fed with raw stdout/stderr chunks; the split on \r and \n happens here
        if self.done:
            return
        for part in re.split(r"[\r\n]+", text):
            line = _strip_ansi(part).strip()
            if not line:
                continue
            if _RE_VERIFY_LINE.search(line):
                self.phase = "verify"
                self.step = line.strip().lstrip("- ").rstrip(".")
                self.heartbeat()
            if _RE_EXTRACT_LINE.search(line):
                self.phase = "extract"
            step = _RE_EXTRACT_STEP.match(line)
            if step:
                self.step = f"{step.group(1).capitalize()} {step.group('what')}"
                self.heartbeat()
            guessed = _guess_fw_key(line, self.known_keys)
            # A job knows which firmwares it touches, so a model named in passing
            # by the environment banner must not steal the bar
            if guessed and (not self.known_keys or guessed in self.known_keys):
                self.current_key = guessed
            progress = _parse_progress(line)
            key = self.current_key or (self.known_keys[0] if len(self.known_keys) == 1 else "")
            if not progress or not key:
                continue
            pct = int(progress.get("percent", -1))
            now = time.time()
            last_pct, last_ts = self._last_emit.get(key, (-1, 0.0))
            # A fresh bar after a finished one is the next step of the same tool
            if self.phase == "download" and last_pct >= 99 and 0 <= pct <= 5:
                self.phase = "decrypt"
                self.step = ""
            if pct >= 0 and pct == last_pct and (now - last_ts) < 0.9:
                continue
            self._last_emit[key] = (pct, now)
            self.started_keys.add(key)
            self._started_at.setdefault(key, time.time())
            effective_elapsed = int(time.time() - self._started_at[key])
            set_progress(
                self.scope,
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
        # Heartbeat keeps the bar alive while extract prints no percentage at all
        if self.done:
            return
        targets = self.started_keys or set(self.known_keys)
        now = time.time()
        written = {}
        if self.probe:
            total, speed = self.probe.sample()
            if total:
                written = {"downloaded_bytes": total, "speed_bps": speed}
        for key in targets:
            self._started_at.setdefault(key, now)
            last_pct = self._last_emit.get(key, (0, 0.0))[0]
            # The step names one firmware, so showing it on the other card would
            # claim work that is not happening there
            step = self.step if (not self.current_key or key == self.current_key) else ""
            set_progress(
                self.scope,
                key,
                {
                    "type": "progress",
                    "status": "running",
                    "phase": self.phase,
                    "job_id": self.job_id,
                    "percent": max(0, last_pct),
                    "indeterminate": last_pct <= 0,
                    "message": step,
                    "elapsed_sec": int(now - self._started_at[key]),
                    **written,
                },
            )

    def finalize(self, ok: bool, status: str | None = None):
        if self.done:
            return
        self.done = True
        # Settle the entry as completed/failed; terminal entries
        # get a short TTL in Redis so they cannot resurrect after a reload
        targets = sorted(self.started_keys or set(self.known_keys))
        if not targets:
            return
        final_status = status or ("completed" if ok else "failed")
        for key in targets:
            set_progress(
                self.scope,
                key,
                {
                    "type": "progress",
                    "status": final_status,
                    "phase": self.phase,
                    "job_id": self.job_id,
                    "percent": 100 if ok else self._last_emit.get(key, (0, 0.0))[0],
                    "indeterminate": False,
                },
            )


def _job_status(db, job_id: str) -> str:
    # Cancellation is written by a different session, so the identity map has to
    # be dropped or we keep reading the status we wrote ourselves
    job = db.get(BuildJob, job_id)
    if not job:
        return ""
    db.refresh(job)
    return str(job.status or "")


def _run_operation_job(job_id: str, operation):
    # Shared wrapper for operation jobs: status lifecycle, log_path, error handling
    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return
        if job.status == "canceled":
            return
        ctx = _workspace_context(db, job)
        ctx.logs.mkdir(parents=True, exist_ok=True)
        op_name = _safe_target(job.operation_name or "operation")
        log_file = ctx.logs / f"{op_name}-{job.id}.log"
        job.status = "running"
        job.started_at = _now()
        job.log_path = str(log_file)
        db.commit()
        publish_job_event(job)
        operation(log_file, ctx)
        if _job_status(db, job_id) == "canceled":
            return
        job = db.get(BuildJob, job_id)
        if job:
            job.status = "succeeded"
            job.return_code = 0
            job.finished_at = _now()
            db.commit()
            publish_job_event(job)
            notify_job(job)
    except Exception as exc:
        if _job_status(db, job_id) == "canceled":
            return
        job = db.get(BuildJob, job_id)
        if job:
            job.status = "failed"
            job.error = _redact(exc)
            job.return_code = 1
            job.finished_at = _now()
            db.commit()
            publish_job_event(job)
            notify_job(job)
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
    # Extract FW from ODIN cache into out/fw, always with --force for consistent result
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        cmd = (
            f"cd {shlex.quote(str(ctx.root))} && "
            f"source buildenv.sh {shlex.quote(target_codename)} && "
            f"scripts/extract_fw.sh --ignore-source --ignore-target --force "
            f"{shlex.quote(fw_key.replace('_', '/', 1) + '/350000000000000')}"
        )
        odin_dir = ctx.out / "odin" / fw_key
        fw_dir = ctx.out / "fw" / fw_key
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        tracker = _FirmwareProgressTracker(job_id, ctx.fw_scope, [fw_key.upper()], phase="extract", watch_path=fw_dir)
        tracker.heartbeat()
        with log_file.open("ab") as lf:
            lf.write(f"[extract] fw_key={fw_key} target={target_codename}\n".encode())
            lf.flush()
            proc = subprocess.Popen(
                ["bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=0,
                preexec_fn=os.setsid,
            )
            _set_job_pid(job_id, proc.pid)
            assert proc.stdout
            ok = False
            canceled = False
            try:
                last_heartbeat = 0.0
                while True:
                    # Silence is normal here: extraction prints nothing for
                    # minutes, and a read that blocks would freeze the bar with it
                    if not select.select([proc.stdout.fileno()], [], [], 0.5)[0]:
                        now = time.time()
                        if now - last_heartbeat >= 1.0:
                            tracker.heartbeat()
                            last_heartbeat = now
                        continue
                    # Reading from the descriptor hands over whatever is there;
                    # a sized read on the text wrapper waits for a full buffer
                    # and holds sparse output back
                    raw = os.read(proc.stdout.fileno(), 4096)
                    if not raw:
                        break
                    chunk = raw.decode("utf-8", errors="ignore")
                    lf.write(chunk.encode("utf-8", errors="ignore"))
                    lf.flush()
                    tracker.feed(chunk)
                    now = time.time()
                    if now - last_heartbeat >= 1.0:
                        tracker.heartbeat()
                        last_heartbeat = now
                rc = proc.wait()
                db = SessionLocal()
                try:
                    canceled = _job_status(db, job_id) == "canceled"
                finally:
                    db.close()
                if rc != 0 and not canceled:
                    raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
                ok = rc == 0
            finally:
                _set_job_pid(job_id, None)
                tracker.finalize(ok, status="canceled" if canceled else None)
                _invalidate_dir_size_cache_paths([odin_dir, fw_dir, ctx.out / "odin", ctx.out / "fw"])

    _run_operation_job(job_id, _op)


def run_download_samsung_fw_job(job_id: str, target_codename: str, kind: str, fw_keys: list[str] | None = None):
    # Downloading is its own operation so a firmware can be fetched ahead of a
    # build, which is the slow part of a first run
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        flags = []
        if kind == "source":
            flags.append("--ignore-target")
        elif kind == "target":
            flags.append("--ignore-source")
        cmd = (
            f"cd {shlex.quote(str(ctx.root))} && "
            f"source buildenv.sh {shlex.quote(target_codename)} && "
            f"scripts/download_fw.sh {' '.join(flags)}"
        ).strip()
        odin_dir = ctx.out / "odin"
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        tracker = _FirmwareProgressTracker(
            job_id, ctx.fw_scope, list(fw_keys or []), phase="download", watch_path=ctx.out / "fw"
        )
        tracker.heartbeat()
        with log_file.open("ab") as lf:
            lf.write(f"[download] target={target_codename} kind={kind}\n".encode())
            lf.flush()
            proc = subprocess.Popen(
                ["bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=0,
                preexec_fn=os.setsid,
            )
            _set_job_pid(job_id, proc.pid)
            assert proc.stdout
            ok = False
            canceled = False
            try:
                last_heartbeat = 0.0
                while True:
                    # Silence is normal here: extraction prints nothing for
                    # minutes, and a read that blocks would freeze the bar with it
                    if not select.select([proc.stdout.fileno()], [], [], 0.5)[0]:
                        now = time.time()
                        if now - last_heartbeat >= 1.0:
                            tracker.heartbeat()
                            last_heartbeat = now
                        continue
                    # Reading from the descriptor hands over whatever is there;
                    # a sized read on the text wrapper waits for a full buffer
                    # and holds sparse output back
                    raw = os.read(proc.stdout.fileno(), 4096)
                    if not raw:
                        break
                    chunk = raw.decode("utf-8", errors="ignore")
                    lf.write(chunk.encode("utf-8", errors="ignore"))
                    lf.flush()
                    tracker.feed(chunk)
                    now = time.time()
                    if now - last_heartbeat >= 1.0:
                        tracker.heartbeat()
                        last_heartbeat = now
                rc = proc.wait()
                db = SessionLocal()
                try:
                    canceled = _job_status(db, job_id) == "canceled"
                finally:
                    db.close()
                if rc != 0 and not canceled:
                    raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
                ok = rc == 0
            finally:
                _set_job_pid(job_id, None)
                tracker.finalize(ok, status="canceled" if canceled else None)
                _invalidate_dir_size_cache_paths([odin_dir, ctx.out / "fw"])

    _run_operation_job(job_id, _op)


def _target_config_value(root: Path, codename: str, key: str) -> str:
    path = root / "target" / codename / "config.sh"
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return ""
    match = re.search(rf"^{re.escape(key)}=\"?([^\"\n]*)\"?", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _incremental_zip_cmd(root: Path, target_codename: str, base_path: str, target_files_path: str) -> str:
    # The generated config is a snapshot from whichever build ran last, and a key
    # added to the target afterwards is still "none" there. imgdiff needs the
    # cache size to bound a patch, and that size describes the device rather than
    # the images being packed, so it is safe to refresh
    refresh = ""
    cache_size = _target_config_value(root, target_codename, "TARGET_CACHE_PARTITION_SIZE")
    if cache_size:
        refresh = (
            "sed -i "
            + shlex.quote(f"s|^TARGET_CACHE_PARTITION_SIZE=.*|TARGET_CACHE_PARTITION_SIZE={_sh_dq(cache_size)}|")
            + " out/config.sh && "
        )
    return (
        f"cd {shlex.quote(str(root))} && "
        f"{refresh}"
        f"source buildenv.sh {shlex.quote(target_codename)} && "
        f"scripts/build_flashable_zip.sh --incremental {shlex.quote(base_path)} "
        f"{shlex.quote(target_files_path)}"
    )


def _pack_incremental_zip(
    job_id: str,
    ctx: ws_lib.WorkspaceRef,
    log_file: Path,
    target_codename: str,
    base_path: str,
    target_files_path: str,
) -> int:
    # Runs inside the build job that just produced the archive, so the whole run
    # stays one job with one log instead of a second job started by hand
    cmd = _incremental_zip_cmd(ctx.root, target_codename, base_path, target_files_path)
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    with log_file.open("ab") as lf:
        lf.write(f"[incremental] base={Path(base_path).name} target={Path(target_files_path).name}\n".encode())
        lf.flush()
        proc = subprocess.Popen(
            ["bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=0,
            preexec_fn=os.setsid,
        )
        _set_job_pid(job_id, proc.pid)
        assert proc.stdout
        try:
            while True:
                raw = os.read(proc.stdout.fileno(), 4096)
                if not raw:
                    break
                lf.write(raw)
                lf.flush()
            return proc.wait()
        finally:
            _set_job_pid(job_id, None)


def run_incremental_zip_job(job_id: str, base_path: str, target_files_path: str, target_codename: str):
    # Packs the difference between two builds that already exist, so nothing has
    # to be rebuilt to change which one the update is measured against
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        cmd = _incremental_zip_cmd(ctx.root, target_codename, base_path, target_files_path)
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        started = time.time()
        with log_file.open("ab") as lf:
            lf.write(f"[incremental] base={Path(base_path).name} target={Path(target_files_path).name}\n".encode())
            lf.flush()
            proc = subprocess.Popen(
                ["bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=0,
                preexec_fn=os.setsid,
            )
            _set_job_pid(job_id, proc.pid)
            assert proc.stdout
            canceled = False
            try:
                while True:
                    raw = os.read(proc.stdout.fileno(), 4096)
                    if not raw:
                        break
                    chunk = raw.decode("utf-8", errors="ignore")
                    lf.write(chunk.encode("utf-8", errors="ignore"))
                    lf.flush()
                rc = proc.wait()
                db = SessionLocal()
                try:
                    canceled = _job_status(db, job_id) == "canceled"
                    if rc == 0 and not canceled:
                        artifact = _pick_newest(ctx.out, "UN1CA_*INCREMENTAL*.zip", started)
                        if artifact:
                            row = db.get(BuildJob, job_id)
                            if row:
                                row.artifact_path = artifact
                                db.commit()
                finally:
                    db.close()
                if rc != 0 and not canceled:
                    raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
            finally:
                _set_job_pid(job_id, None)
                _invalidate_dir_size_cache_paths([ctx.out])

    _run_operation_job(job_id, _op)


def run_delete_samsung_fw_job(job_id: str, fw_type: str, fw_key: str):
    # Delete cached Odin/FW entry from out tree
    def _delete(log_file: Path, ctx: ws_lib.WorkspaceRef):
        base = ctx.out / ("odin" if fw_type == "odin" else "fw")
        target = base / fw_key
        with log_file.open("ab") as lf:
            lf.write(f"[delete] fw_type={fw_type} fw_key={fw_key} path={target}\n".encode())
            lf.flush()
        if not target.exists():
            with log_file.open("ab") as lf:
                lf.write(b"[delete] path does not exist, nothing to do\n")
            return
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            with log_file.open("ab") as lf:
                lf.write(f"[delete] removed directory: {target}\n".encode())
        else:
            target.unlink(missing_ok=True)
            with log_file.open("ab") as lf:
                lf.write(f"[delete] removed file: {target}\n".encode())
        _invalidate_dir_size_cache_paths([target, base])

    _run_operation_job(job_id, _delete)


def _git_auth_args(git_url: str, username: str, token: str) -> list[str]:
    if not token:
        return []
    try:
        parsed = urlparse(git_url)
        if not parsed.scheme.startswith("http") or not parsed.hostname:
            return []
        user = username or "oauth2"
        base = f"{parsed.scheme}://{parsed.hostname}/"
        auth_prefix = f"{parsed.scheme}://{quote(user)}:{quote(token)}@{parsed.hostname}/"
        return ["-c", f"url.{auth_prefix}.insteadOf={base}"]
    except Exception:
        return []


def _git_cfg_prefix(git_args: list[str]) -> str:
    if not git_args:
        return "git"
    return "git " + " ".join(shlex.quote(x) for x in git_args)


def _safe_git_url(url: str) -> str:
    if "@" not in url or not url.startswith(("http://", "https://")):
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://{rest.split('@', 1)[1]}"


def _current_origin(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-c", "safe.directory=*", "-C", str(root), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return _safe_git_url(out)
    except Exception:
        return ""


def _is_mount(path: Path) -> bool:
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def _checkout_cmd(root: Path, git_cfg: str, git_ref: str) -> str:
    return (
        f"cd {shlex.quote(str(root))} && "
        f"{git_cfg} -c safe.directory=* fetch --all --tags --prune && "
        f"{{ {git_cfg} -c safe.directory=* fetch origin {shlex.quote(git_ref)} --prune || true; }} && "
        f"{git_cfg} -c safe.directory=* checkout -f {shlex.quote(git_ref)} && "
        f"if {git_cfg} -c safe.directory=* rev-parse --verify origin/{shlex.quote(git_ref)} >/dev/null 2>&1; then "
        f"{git_cfg} -c safe.directory=* reset --hard origin/{shlex.quote(git_ref)}; fi && "
        f"{git_cfg} -c safe.directory=* submodule sync --recursive && "
        f"{git_cfg} -c safe.directory=* submodule update --init --recursive --no-recommend-shallow --jobs 8"
    )


def _replace_tree(src: Path, dst: Path, log_file: Path):
    # Swap a freshly built tree in for the old one. Renaming is atomic, but the
    # workspace root can be a bind-mount point, and those cannot be renamed
    if _is_mount(dst):
        with log_file.open("ab") as lf:
            lf.write(f"[repo] {dst} is a mount point, swapping contents in place\n".encode())
        for item in dst.iterdir():
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        for item in src.iterdir():
            os.replace(item, dst / item.name)
        shutil.rmtree(src, ignore_errors=True)
        return
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def run_repo_clone_job(job_id: str, fresh: bool = False):
    # Clone is idempotent by default: an existing checkout of the same remote is
    # fast-forwarded instead of being wiped and re-downloaded. A full re-clone is
    # an explicit choice, and even then the old tree survives until the new one
    # is complete
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        clear_repo_progress(ctx.id)
        git_url = ctx.git_url
        if not git_url:
            raise RuntimeError("Workspace has no git url configured")
        git_args = _git_auth_args(git_url, ctx.git_username, ctx.git_token)
        git_cfg = _git_cfg_prefix(git_args)
        safe_url = _safe_git_url(git_url)
        root = ctx.root

        existing_origin = _current_origin(root) if (root / ".git").is_dir() else ""
        same_remote = bool(existing_origin) and existing_origin == safe_url
        if same_remote and not fresh:
            with log_file.open("ab") as lf:
                lf.write(f"[repo] existing checkout of {safe_url} found at {root}, updating in place\n".encode())
            cmd = _checkout_cmd(root, git_cfg, ctx.git_ref)
            tracker = _GitProgressTracker(ctx.id, "update", f"Update {safe_url} ({ctx.git_ref})")
            rc = _stream_command_with_progress(
                ["bash", "-lc", cmd],
                log_file=log_file,
                env=env,
                tracker=tracker,
                on_started=lambda pid: _set_job_pid(job_id, pid),
            )
            if rc != 0:
                raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
            _invalidate_dir_size_cache_paths([root])
            set_repo_progress(
                ctx.id,
                {
                    "type": "progress",
                    "status": "completed",
                    "stage": "update",
                    "title": "Repository updated",
                    "percent": 100,
                },
            )
            return

        if existing_origin and not same_remote:
            with log_file.open("ab") as lf:
                lf.write(f"[repo] remote changed ({existing_origin} -> {safe_url}), full clone required\n".encode())

        # The suffix is per attempt, not per job, so a retry never lands in a
        # directory an earlier attempt is still writing to
        staging = ws_lib.workspaces_root() / f".clone-{job_id}-{uuid.uuid4().hex[:8]}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        try:
            tracker = _GitProgressTracker(ctx.id, "clone", f"Clone {safe_url}", base=0, span=70)
            rc = _stream_command_with_progress(
                ["git", *git_args, "clone", "--progress", "--recurse-submodules", git_url, str(staging)],
                log_file=log_file,
                env=env,
                tracker=tracker,
                on_started=lambda pid: _set_job_pid(job_id, pid),
            )
            if rc != 0:
                raise subprocess.CalledProcessError(rc, ["git", "clone"])

            setup_cmd = _checkout_cmd(staging, git_cfg, ctx.git_ref)
            tracker = _GitProgressTracker(
                ctx.id,
                "submodules",
                f"Checkout {ctx.git_ref} and sync submodules",
                base=70,
                span=30,
            )
            rc = _stream_command_with_progress(
                ["bash", "-lc", setup_cmd],
                log_file=log_file,
                env=env,
                tracker=tracker,
                on_started=lambda pid: _set_job_pid(job_id, pid),
            )
            if rc != 0:
                raise subprocess.CalledProcessError(rc, ["bash", "-lc", setup_cmd])

            # The out tree holds tens of GB of firmware; carry it over instead of
            # forcing a re-download. It moves only after the clone has succeeded
            old_out = root / "out"
            if old_out.exists():
                staging_out = staging / "out"
                if staging_out.exists():
                    shutil.rmtree(staging_out, ignore_errors=True)
                try:
                    os.replace(old_out, staging_out)
                except OSError:
                    shutil.move(str(old_out), str(staging_out))
                with log_file.open("ab") as lf:
                    lf.write(b"[repo] preserved existing out/ tree\n")

            _replace_tree(staging, root, log_file)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        _invalidate_dir_size_cache_paths([root])
        set_repo_progress(
            ctx.id,
            {
                "type": "progress",
                "status": "completed",
                "stage": "clone",
                "title": "Repository clone completed",
                "percent": 100,
            },
        )

    _run_operation_job(job_id, _op)


def run_repo_pull_job(job_id: str):
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        if not (ctx.root / ".git").is_dir():
            raise RuntimeError("Repository is not cloned yet")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        clear_repo_progress(ctx.id)
        git_args = _git_auth_args(ctx.git_url, ctx.git_username, ctx.git_token)
        git_cfg = _git_cfg_prefix(git_args)
        cmd = (
            f"cd {shlex.quote(str(ctx.root))} && "
            f"{git_cfg} -c safe.directory=* fetch --all --tags --prune && "
            f"{{ {git_cfg} -c safe.directory=* fetch origin {shlex.quote(ctx.git_ref)} --prune || true; }} && "
            f"{git_cfg} -c safe.directory=* checkout -f {shlex.quote(ctx.git_ref)} && "
            f"if {git_cfg} -c safe.directory=* rev-parse --verify "
            f"origin/{shlex.quote(ctx.git_ref)} >/dev/null 2>&1; then "
            f"{git_cfg} -c safe.directory=* reset --hard origin/{shlex.quote(ctx.git_ref)}; fi"
        )
        tracker = _GitProgressTracker(ctx.id, "pull", f"Update repository ({ctx.git_ref})")
        rc = _stream_command_with_progress(
            ["bash", "-lc", cmd],
            log_file=log_file,
            env=env,
            tracker=tracker,
            on_started=lambda pid: _set_job_pid(job_id, pid),
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
        _invalidate_dir_size_cache_paths([ctx.root])
        set_repo_progress(
            ctx.id,
            {"type": "progress", "status": "completed", "stage": "pull", "title": "Repository updated", "percent": 100},
        )

    _run_operation_job(job_id, _op)


def run_repo_submodules_job(job_id: str):
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        if not (ctx.root / ".git").is_dir():
            raise RuntimeError("Repository is not cloned yet")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        clear_repo_progress(ctx.id)
        git_args = _git_auth_args(ctx.git_url, ctx.git_username, ctx.git_token)
        git_cfg = _git_cfg_prefix(git_args)
        cmd = (
            f"cd {shlex.quote(str(ctx.root))} && "
            f"{git_cfg} -c safe.directory=* submodule sync --recursive && "
            f"{git_cfg} -c safe.directory=* submodule update --init --recursive --no-recommend-shallow --jobs 8"
        )
        tracker = _GitProgressTracker(ctx.id, "submodules", "Update submodules")
        rc = _stream_command_with_progress(
            ["bash", "-lc", cmd],
            log_file=log_file,
            env=env,
            tracker=tracker,
            on_started=lambda pid: _set_job_pid(job_id, pid),
        )
        if rc != 0:
            raise subprocess.CalledProcessError(rc, ["bash", "-lc", cmd])
        _invalidate_dir_size_cache_paths([ctx.root])
        set_repo_progress(
            ctx.id,
            {
                "type": "progress",
                "status": "completed",
                "stage": "submodules",
                "title": "Submodules updated",
                "percent": 100,
            },
        )

    _run_operation_job(job_id, _op)


def run_repo_delete_job(job_id: str, mode: str = "repo_only"):
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        root = ctx.root
        clear_repo_progress(ctx.id)
        with log_file.open("ab") as lf:
            lf.write(f"[repo-delete] mode={mode} path={root}\n".encode())
            lf.flush()
        if root.exists():
            for item in root.iterdir():
                if mode != "repo_with_out" and item.name == "out":
                    continue
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        root.mkdir(parents=True, exist_ok=True)
        _invalidate_dir_size_cache_paths([root])
        title = "Repository removed with out" if mode == "repo_with_out" else "Repository removed, out preserved"
        set_repo_progress(
            ctx.id,
            {"type": "progress", "status": "completed", "stage": "delete", "title": title, "percent": 100},
        )

    _run_operation_job(job_id, _op)


def run_workspace_delete_job(job_id: str, target_workspace_id: str, delete_files: bool):
    # The workspace row is dropped by the API; this job only reclaims the disk
    def _op(log_file: Path, ctx: ws_lib.WorkspaceRef):
        db = SessionLocal()
        try:
            ws = db.get(Workspace, target_workspace_id)
        finally:
            db.close()
        with log_file.open("ab") as lf:
            lf.write(f"[workspace-delete] id={target_workspace_id} delete_files={delete_files}\n".encode())
            lf.flush()
        if not delete_files:
            return
        root = ws_lib.root_path(ws) if ws is not None else None
        if root is None or not root.exists():
            with log_file.open("ab") as lf:
                lf.write(b"[workspace-delete] nothing on disk to remove\n")
            return
        if _is_mount(root):
            for item in root.iterdir():
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        else:
            shutil.rmtree(root, ignore_errors=True)
        with log_file.open("ab") as lf:
            lf.write(f"[workspace-delete] removed {root}\n".encode())
        _invalidate_dir_size_cache_paths([root])

    _run_operation_job(job_id, _op)


def run_stop_job_task(job_id: str, signal_type: str = "sigterm"):
    # Worker-side stop: only worker can safely signal build process group
    def _is_alive(pid: int) -> bool:
        # Check the process group first: the build runs in its own pgid
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
        # Fallback: check process directly
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
        db.refresh(job)
        if job.status in {"succeeded", "failed", "reused", "canceled"}:
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

            # Confirm termination before marking canceled. If still alive, keep running so user can retry stop
            timeout_sec = 5 if signal_type == "sigkill" else 25
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                if not _is_alive(job.process_pid):
                    break
                time.sleep(0.5)

            if not _is_alive(job.process_pid):
                job.status = "canceled"
                job.error = (
                    "Build canceled by user (SIGKILL)"
                    if signal_type == "sigkill"
                    else "Build canceled by user (SIGTERM)"
                )
                job.finished_at = _now()
                job.process_pid = None
            else:
                job.error = (
                    "Stop requested by user "
                    f"({signal_type.upper()}), but process is still running. Retry stop if needed."
                )
            db.commit()
            publish_job_event(job)
            return
        if job.status == "running" and not job.process_pid:
            job.error = "Stop requested by user, but build PID is missing. Please retry stop or check worker logs."
            db.commit()
            return
    finally:
        db.close()


def _pick_newest(out_dir: Path, pattern: str, started_at: float) -> str | None:
    matches = []
    for path in glob.glob(str(out_dir / pattern)):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime + 1.0 >= started_at:
            matches.append((mtime, path))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _pick_artifact(out_dir: Path, started_at: float) -> str | None:
    # Only a zip produced by this run counts. Without the mtime guard a build
    # that produced nothing would happily adopt someone else's older artifact
    matches = []
    for path in glob.glob(str(out_dir / "UN1CA_*.zip")):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime + 1.0 >= started_at:
            matches.append((mtime, path))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def run_build_job(job_id: str):
    # Main build pipeline: overrides, extra mods, debloat patching, make_rom, artifact detect
    db = SessionLocal()
    extra_mods_tmp_dir = None
    injected_mod_dirs: list[Path] = []
    replaced_mod_dirs: list[tuple[Path, Path]] = []
    mods_override_state: dict | None = None
    debloat_override_paths: tuple[Path, Path] | None = None
    ff_override_paths: tuple[Path, Path] | None = None
    ctx: ws_lib.WorkspaceRef | None = None
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return
        if job.status == "canceled":
            return

        ctx = _workspace_context(db, job)
        ctx.logs.mkdir(parents=True, exist_ok=True)
        log_file = ctx.logs / f"{_safe_target(job.target)}-{job.id}.log"

        job.status = "running"
        job.started_at = _now()
        job.log_path = str(log_file)
        db.commit()
        publish_job_event(job)
        run_started_at = time.time()

        flags = []
        if job.force:
            flags.append("--force")
        # The build script makes the target-files zip by default and the flashable
        # one only when asked, so wanting a rom means passing a flag rather than
        # withholding one. Skipping target files drops both, which is why the two
        # options cannot be combined
        if job.skip_target_files:
            flags.append("--no-target-files")
        elif not job.no_rom_zip:
            flags.append("--build-rom-zip")

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
        # buildenv generates out/config.sh and exports every value in it, and the
        # build reads the exported variable rather than the file, so the version
        # has to be replaced in both. The generated file is build output, not the
        # checkout, so rewriting it there neither touches upstream sources nor
        # dirties the tree
        rewrite_version = ""
        if job.version_major is not None and job.version_minor is not None and job.version_patch is not None:
            rewrite_version = (
                "sed -i "
                + shlex.quote(f"s|^ROM_VERSION=.*|ROM_VERSION={_sh_dq(rom_version)}|")
                + " out/config.sh && export ROM_VERSION="
                + shlex.quote(rom_version)
            )

        if job.extra_mods_archive_path and Path(job.extra_mods_archive_path).exists():
            # Extra mods exist for this one build only:
            # - a new module is just dropped into unica/mods
            # - a name clash replaces the original module, which is restored in finally
            extra_mods_tmp_dir = Path(settings.data_dir) / "tmp-extra-mods" / job.id
            extra_mods_tmp_dir.mkdir(parents=True, exist_ok=True)
            validated = validate_mods_archive(Path(job.extra_mods_archive_path), extra_mods_tmp_dir)
            modules_root = Path(validated["modules_root"])
            target_mods_dir = ctx.root / "unica" / "mods"
            target_mods_dir.mkdir(parents=True, exist_ok=True)
            backup_mods_root = extra_mods_tmp_dir / "_original_mods_backup"
            backup_mods_root.mkdir(parents=True, exist_ok=True)
            for module_dir in sorted(modules_root.iterdir(), key=lambda x: x.name):
                if not module_dir.is_dir() or not (module_dir / "module.prop").is_file():
                    continue
                dst = target_mods_dir / module_dir.name
                if dst.exists():
                    backup_dst = backup_mods_root / module_dir.name
                    if backup_dst.exists():
                        shutil.rmtree(backup_dst, ignore_errors=True)
                    shutil.move(str(dst), str(backup_dst))
                    replaced_mod_dirs.append((dst, backup_dst))
                shutil.copytree(module_dir, dst, symlinks=True)
                if not any(original == dst for original, _ in replaced_mod_dirs):
                    injected_mod_dirs.append(dst)
            if "--force" not in flags:
                flags.append("--force")
        if job.debloat_disabled_json or job.debloat_add_system_json or job.debloat_add_product_json:
            # Debloat overrides are temporary too: patch before the build, restore in finally
            try:
                disabled_ids = json.loads(job.debloat_disabled_json or "[]")
                add_system = json.loads(job.debloat_add_system_json or "[]")
                add_product = json.loads(job.debloat_add_product_json or "[]")
                if isinstance(disabled_ids, list) and isinstance(add_system, list) and isinstance(add_product, list):
                    debloat_override_paths = apply_debloat_overrides(
                        ctx.root,
                        disabled_ids,
                        add_system,
                        add_product,
                    )
                if debloat_override_paths and "--force" not in flags:
                    flags.append("--force")
            except Exception:
                pass
        if job.mods_disabled_json:
            try:
                mods_disabled = json.loads(job.mods_disabled_json or "[]")
                if isinstance(mods_disabled, list):
                    mods_override_state = apply_mods_disabled_overrides(ctx.root, mods_disabled)
                if mods_override_state and "--force" not in flags:
                    flags.append("--force")
            except Exception:
                pass
        if job.ff_overrides_json:
            try:
                overrides = json.loads(job.ff_overrides_json or "{}")
                if isinstance(overrides, dict) and job.source_firmware and job.target_firmware:
                    _ensure_fw_extracted(ctx, job.target, job.source_firmware, job.target_firmware)
                    fw_key = _firmware_key_from_value(job.target_firmware)
                    ff_xml = ctx.out / "fw" / fw_key / "system/system/etc/floating_feature.xml"
                    ff_override_paths = apply_ff_overrides(ff_xml, overrides)
                    if ff_override_paths and "--force" not in flags:
                        flags.append("--force")
            except Exception:
                pass

        cmd = f"cd {shlex.quote(str(ctx.root))} && source buildenv.sh {shlex.quote(job.target)} && "
        if override_exports:
            cmd += " && ".join(override_exports) + " && "
        if rewrite_version:
            cmd += rewrite_version + " && "
        cmd += f"scripts/make_rom.sh {' '.join(shlex.quote(x) for x in flags)}"

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        tracker = _FirmwareProgressTracker(
            job.id,
            ctx.fw_scope,
            [
                _firmware_key_from_value(job.source_firmware),
                _firmware_key_from_value(job.target_firmware),
            ],
            phase="download",
        )

        rc = 1
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
            current_stage = "start"
            current_pct = 0
            set_build_progress(
                job.id,
                {
                    "type": "progress",
                    "status": "running",
                    "stage": current_stage,
                    "percent": current_pct,
                    "indeterminate": True,
                    "workspace_id": ctx.id,
                },
            )
            fw_done = False
            try:
                last_heartbeat = 0.0
                while True:
                    # Silence is normal here: extraction prints nothing for
                    # minutes, and a read that blocks would freeze the bar with it
                    if not select.select([proc.stdout.fileno()], [], [], 0.5)[0]:
                        now = time.time()
                        if now - last_heartbeat >= 1.0:
                            tracker.heartbeat()
                            last_heartbeat = now
                        continue
                    # Reading from the descriptor hands over whatever is there;
                    # a sized read on the text wrapper waits for a full buffer
                    # and holds sparse output back
                    raw = os.read(proc.stdout.fileno(), 4096)
                    if not raw:
                        break
                    chunk = raw.decode("utf-8", errors="ignore")
                    lf.write(chunk.encode("utf-8", errors="ignore"))
                    lf.flush()
                    tracker.feed(chunk)
                    for line in re.split(r"[\r\n]+", chunk):
                        text = _strip_ansi(line).strip()
                        if not text:
                            continue
                        for stage, pct, pattern in _BUILD_STAGE_RULES:
                            if not pattern.search(text):
                                continue
                            # Past the work dir the firmware is done with, and its
                            # card should stop showing a bar for the rest of the build
                            if stage not in _FIRMWARE_BUILD_STAGES and not fw_done:
                                fw_done = True
                                tracker.finalize(True)
                            if pct >= current_pct:
                                current_stage = stage
                                current_pct = pct
                                set_build_progress(
                                    job.id,
                                    {
                                        "type": "progress",
                                        "status": "running",
                                        "stage": current_stage,
                                        "percent": current_pct,
                                        "indeterminate": False,
                                        "message": text[:200],
                                        "workspace_id": ctx.id,
                                    },
                                )
                            break
                    now = time.time()
                    if now - last_heartbeat >= 1.0:
                        tracker.heartbeat()
                        last_heartbeat = now
                rc = proc.wait()
                ok = rc == 0
            finally:
                canceled = _job_status(db, job_id) == "canceled"
                status = "canceled" if canceled else ("completed" if ok else "failed")
                tracker.finalize(ok, status="canceled" if canceled else None)
                set_build_progress(
                    job.id,
                    {
                        "type": "progress",
                        "status": status,
                        "stage": "done" if ok else current_stage,
                        "percent": 100 if ok else current_pct,
                        "indeterminate": False,
                        "workspace_id": ctx.id,
                    },
                )

        job = db.get(BuildJob, job_id)
        if not job:
            return
        db.refresh(job)
        job.process_pid = None
        job.return_code = rc
        job.finished_at = _now()
        if job.status == "canceled":
            job.error = job.error or "Build canceled by user"
        elif rc == 0:
            job.status = "succeeded"
            if not job.no_rom_zip:
                artifact = _pick_artifact(ctx.out, run_started_at)
                if artifact:
                    job.artifact_path = artifact
            if not job.skip_target_files:
                # Kept on the job so an incremental zip can be packed later
                # without hunting for the archive this build produced
                target_files = _pick_newest(ctx.out, f"{job.target}_*-target_files.zip", run_started_at)
                if target_files:
                    job.target_files_path = target_files
                if job.incremental_base_job_id and target_files:
                    base = db.get(BuildJob, job.incremental_base_job_id)
                    base_path = str(base.target_files_path or "") if base else ""
                    if base_path and Path(base_path).is_file():
                        rc = _pack_incremental_zip(job_id, ctx, log_file, job.target, base_path, target_files)
                        db.refresh(job)
                        if rc == 0:
                            artifact = _pick_newest(ctx.out, "UN1CA_*INCREMENTAL*.zip", run_started_at)
                            if artifact:
                                job.artifact_path = artifact
                        else:
                            job.status = "failed"
                            job.error = f"Incremental zip failed with return code {rc}"
                    else:
                        job.status = "failed"
                        job.error = "Target-files zip of the base build is gone"
        else:
            job.status = "failed"
            job.error = f"Build failed with return code {rc}"
        db.commit()
        publish_job_event(job)
        notify_job(job)

    except Exception as exc:
        job = db.get(BuildJob, job_id)
        if job:
            db.refresh(job)
            if job.status != "canceled":
                job.status = "failed"
                job.error = _redact(exc)
            job.finished_at = _now()
            job.process_pid = None
            db.commit()
            publish_job_event(job)
    finally:
        for mod_dir in injected_mod_dirs:
            if mod_dir.exists():
                shutil.rmtree(mod_dir, ignore_errors=True)
        for overridden_path, backup_path in reversed(replaced_mod_dirs):
            if overridden_path.exists():
                shutil.rmtree(overridden_path, ignore_errors=True)
            if backup_path.exists():
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup_path), str(overridden_path))
        if extra_mods_tmp_dir and extra_mods_tmp_dir.exists():
            shutil.rmtree(extra_mods_tmp_dir, ignore_errors=True)
        if debloat_override_paths:
            restore_debloat_file(*debloat_override_paths)
        if mods_override_state:
            restore_mods_overrides(mods_override_state)
        if ff_override_paths:
            restore_ff_overrides(*ff_override_paths)
        job = db.get(BuildJob, job_id)
        if job and job.extra_mods_archive_path and Path(job.extra_mods_archive_path).exists():
            try:
                Path(job.extra_mods_archive_path).unlink(missing_ok=True)
            except Exception:
                pass
        # Build may download/extract firmware and mutate out tree, invalidate size cache keys.
        # Also invalidate source/target fw specific dirs to reflect updated markers/sizes immediately
        if ctx is not None:
            source_key = ""
            target_key = ""
            if job:
                source_key = _firmware_key_from_value(job.source_firmware)
                target_key = _firmware_key_from_value(job.target_firmware)
            paths = [ctx.out / "odin", ctx.out / "fw"]
            if source_key:
                paths.extend([ctx.out / "odin" / source_key, ctx.out / "fw" / source_key])
            if target_key and target_key != source_key:
                paths.extend([ctx.out / "odin" / target_key, ctx.out / "fw" / target_key])
            _invalidate_dir_size_cache_paths(paths)
        db.close()
