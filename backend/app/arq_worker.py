import asyncio

from arq.connections import RedisSettings

from .config import settings
from .queue import ARQ_QUEUE_BUILDS, ARQ_QUEUE_CONTROLS
from .tasks import (
    run_build_job,
    run_delete_samsung_fw_job,
    run_extract_samsung_fw_job,
    run_repo_clone_job,
    run_repo_delete_job,
    run_repo_pull_job,
    run_repo_submodules_job,
    run_stop_job_task,
)


def _redis_settings() -> RedisSettings:
    from urllib.parse import urlparse

    parsed = urlparse(settings.redis_url)
    db = 0
    if parsed.path and parsed.path != "/":
        try:
            db = int(parsed.path.lstrip("/"))
        except ValueError:
            db = 0
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=db,
        username=parsed.username,
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
    )
async def build_job_task(_ctx, job_id: str):
    await asyncio.to_thread(run_build_job, job_id)


async def extract_fw_job_task(_ctx, job_id: str, fw_key: str, target_codename: str):
    await asyncio.to_thread(run_extract_samsung_fw_job, job_id, fw_key, target_codename)


async def delete_fw_job_task(_ctx, job_id: str, fw_type: str, fw_key: str):
    await asyncio.to_thread(run_delete_samsung_fw_job, job_id, fw_type, fw_key)


async def repo_clone_job_task(_ctx, job_id: str, git_url: str, git_ref: str):
    await asyncio.to_thread(run_repo_clone_job, job_id, git_url, git_ref)


async def repo_pull_job_task(_ctx, job_id: str, git_ref: str):
    await asyncio.to_thread(run_repo_pull_job, job_id, git_ref)


async def repo_submodules_job_task(_ctx, job_id: str):
    await asyncio.to_thread(run_repo_submodules_job, job_id)


async def repo_delete_job_task(_ctx, job_id: str, mode: str):
    await asyncio.to_thread(run_repo_delete_job, job_id, mode)


async def stop_job_task(_ctx, job_id: str, signal_type: str):
    await asyncio.to_thread(run_stop_job_task, job_id, signal_type)


class WorkerSettingsBuilds:
    functions = [
        build_job_task,
        extract_fw_job_task,
        delete_fw_job_task,
        repo_clone_job_task,
        repo_pull_job_task,
        repo_submodules_job_task,
        repo_delete_job_task,
    ]
    redis_settings = _redis_settings()
    queue_name = ARQ_QUEUE_BUILDS
    max_jobs = 1
    job_timeout = 60 * 60 * 12


class WorkerSettingsControls:
    functions = [stop_job_task]
    redis_settings = _redis_settings()
    queue_name = ARQ_QUEUE_CONTROLS
    max_jobs = 4
    job_timeout = 60 * 10
