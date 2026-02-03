from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BuildJob(Base):
    __tablename__ = "build_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
