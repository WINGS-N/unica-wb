import signal
import time
from multiprocessing import Process

from rq import Connection, Worker

from app.cleanup import cleanup_stale_build_overrides
from app.queue import redis_conn

stop = False


def _handle_sigterm(signum, frame):  # noqa: ARG001
    global stop
    stop = True


def _run_worker(queues: list[str]):
    with Connection(redis_conn):
        worker = Worker(queues)
        worker.work(with_scheduler=True)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    cleaned = cleanup_stale_build_overrides()
    print(
        f"[worker startup] cleanup: removed {cleaned['uploaded_mod_dirs']} uploaded mod override dirs, "
        f"{cleaned['tmp_extra_mods_dirs']} temp extra-mod dirs",
        flush=True,
    )
    build_proc = Process(target=_run_worker, args=(["builds"],), daemon=False)
    control_proc = Process(target=_run_worker, args=(["controls"],), daemon=False)
    build_proc.start()
    control_proc.start()

    try:
        while not stop:
            if not build_proc.is_alive() or not control_proc.is_alive():
                break
            time.sleep(1)
    finally:
        for p in (build_proc, control_proc):
            if p.is_alive():
                p.terminate()
        for p in (build_proc, control_proc):
            p.join(timeout=10)
