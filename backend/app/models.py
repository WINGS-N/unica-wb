import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Absolute repo root override. Only the migrated legacy workspace uses it;
    # everything else derives its root from workspaces_root/slug
    root_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    git_url: Mapped[str] = mapped_column(Text, default="")
    git_ref: Mapped[str] = mapped_column(String(128), default="")
    git_username: Mapped[str] = mapped_column(String(128), default="")
    git_token: Mapped[str] = mapped_column(Text, default="")

    # When set, out/odin and out/fw are symlinks into the shared firmware cache
    shared_fw_cache: Mapped[bool] = mapped_column(Boolean, default=True)

    source_config_override: Mapped[str] = mapped_column(String(128), default="")
    targets_override: Mapped[str] = mapped_column(Text, default="")

    position: Mapped[int] = mapped_column(Integer, default=0, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class BuildJob(Base):
    __tablename__ = "build_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target: Mapped[str] = mapped_column(String(64), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    source_firmware: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_firmware: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_major: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_patch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_suffix: Mapped[str | None] = mapped_column(String(64), nullable=True)
    build_signature: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    force: Mapped[bool] = mapped_column(Boolean, default=False)
    no_rom_zip: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_target_files: Mapped[bool] = mapped_column(Boolean, default=False)
    target_files_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    job_kind: Mapped[str] = mapped_column(String(32), default="build", index=True)
    operation_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    queue_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    process_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)

    return_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    reused_from_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    extra_mods_archive_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_mods_modules_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    debloat_disabled_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    debloat_add_system_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    debloat_add_product_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    mods_disabled_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ff_overrides_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    # Notifications are rendered while no page is open, so the language the
    # subscriber picked travels with the subscription
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
