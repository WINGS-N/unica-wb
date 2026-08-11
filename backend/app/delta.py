import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

# zstd refuses a --patch-from reference over 2 GB, and a browser cannot hold a
# multi gigabyte dictionary at all, so a delta is built one window at a time
CHUNK_SIZE = 256 * 1024 * 1024
WINDOW_LOG = 27
LEVEL = 3
MANIFEST_NAME = "manifest.json"


def _digest(data: bytes) -> str:
    return hashlib.new("sha512_256", data).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.new("sha512_256")
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_chunk(path: Path, index: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(index * CHUNK_SIZE)
        return handle.read(CHUNK_SIZE)


def _chunk_count(size: int) -> int:
    return (size + CHUNK_SIZE - 1) // CHUNK_SIZE


def build_delta(base: Path, target: Path, output: Path, log=print) -> dict:
    """Writes a zip holding a manifest and one entry per changed chunk."""
    base_size = base.stat().st_size
    target_size = target.stat().st_size
    total_chunks = _chunk_count(target_size)
    base_chunks = _chunk_count(base_size)

    manifest = {
        "version": 1,
        "algorithm": "zstd-patch-from",
        "chunk_size": CHUNK_SIZE,
        "window_log": WINDOW_LOG,
        "hash": "sha512_256",
        "base": {"name": base.name, "size": base_size, "digest": _file_digest(base)},
        "target": {"name": target.name, "size": target_size},
        "chunks": [],
    }

    counts = {"same": 0, "patch": 0, "full": 0}
    with tempfile.TemporaryDirectory(prefix="delta-", dir=str(output.parent)) as tmp:
        work = Path(tmp)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
            for index in range(total_chunks):
                new_data = _read_chunk(target, index)
                entry = {"index": index, "size": len(new_data), "digest": _digest(new_data)}

                old_data = _read_chunk(base, index) if index < base_chunks else b""
                if old_data and old_data == new_data:
                    entry["kind"] = "same"
                    counts["same"] += 1
                    manifest["chunks"].append(entry)
                    continue

                new_path = work / f"new_{index:04d}"
                new_path.write_bytes(new_data)
                name = f"chunk_{index:04d}.zst"
                out_path = work / name

                if old_data:
                    old_path = work / f"old_{index:04d}"
                    old_path.write_bytes(old_data)
                    cmd = [
                        "zstd",
                        f"-{LEVEL}",
                        f"--long={WINDOW_LOG}",
                        "-q",
                        "-f",
                        f"--patch-from={old_path}",
                        str(new_path),
                        "-o",
                        str(out_path),
                    ]
                    entry["kind"] = "patch"
                    counts["patch"] += 1
                else:
                    cmd = ["zstd", f"-{LEVEL}", "-q", "-f", str(new_path), "-o", str(out_path)]
                    entry["kind"] = "full"
                    counts["full"] += 1

                subprocess.run(cmd, check=True, capture_output=True)
                entry["entry"] = name
                entry["entry_size"] = out_path.stat().st_size
                bundle.write(out_path, name)
                manifest["chunks"].append(entry)

                for leftover in (new_path, work / f"old_{index:04d}", out_path):
                    leftover.unlink(missing_ok=True)

                log(f"- chunk {index + 1}/{total_chunks}: {entry['kind']}, {entry.get('entry_size', 0)} bytes")

            bundle.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=True, indent=2))

    return {"counts": counts, "size": output.stat().st_size, "chunks": total_chunks}


def apply_delta(base: Path, bundle_path: Path, output: Path) -> str:
    """Rebuilds the target from a base file and a delta bundle, returns its digest."""
    with zipfile.ZipFile(bundle_path) as bundle:
        manifest = json.loads(bundle.read(MANIFEST_NAME))
        if manifest.get("version") != 1:
            raise ValueError("unsupported delta bundle")
        if _file_digest(base) != manifest["base"]["digest"]:
            raise ValueError("base file does not match the delta")

        chunk_size = int(manifest["chunk_size"])
        window = int(manifest.get("window_log", WINDOW_LOG))
        with tempfile.TemporaryDirectory(prefix="delta-", dir=str(output.parent)) as tmp:
            work = Path(tmp)
            with output.open("wb") as out:
                for entry in manifest["chunks"]:
                    index = int(entry["index"])
                    if entry["kind"] == "same":
                        with base.open("rb") as handle:
                            handle.seek(index * chunk_size)
                            data = handle.read(int(entry["size"]))
                    else:
                        packed = work / entry["entry"]
                        packed.write_bytes(bundle.read(entry["entry"]))
                        restored = work / f"out_{index:04d}"
                        cmd = ["zstd", "-d", "-q", "-f", str(packed), "-o", str(restored)]
                        if entry["kind"] == "patch":
                            old_path = work / f"old_{index:04d}"
                            with base.open("rb") as handle:
                                handle.seek(index * chunk_size)
                                old_path.write_bytes(handle.read(chunk_size))
                            cmd = [
                                "zstd",
                                "-d",
                                "-q",
                                "-f",
                                f"--long={window}",
                                f"--patch-from={old_path}",
                                str(packed),
                                "-o",
                                str(restored),
                            ]
                        subprocess.run(cmd, check=True, capture_output=True)
                        data = restored.read_bytes()
                        for leftover in (packed, restored, work / f"old_{index:04d}"):
                            leftover.unlink(missing_ok=True)

                    if _digest(data) != entry["digest"]:
                        raise ValueError(f"chunk {index} does not match its digest")
                    out.write(data)

    return _file_digest(output)


def zstd_available() -> bool:
    return bool(shutil.which("zstd"))
