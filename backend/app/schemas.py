from datetime import datetime
from pydantic import BaseModel, Field


class BuildJobCreate(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    source_firmware: str | None = Field(default=None, min_length=3, max_length=128)
    target_firmware: str | None = Field(default=None, min_length=3, max_length=128)
    version_major: int | None = Field(default=None, ge=0, le=999)
    version_minor: int | None = Field(default=None, ge=0, le=999)
    version_patch: int | None = Field(default=None, ge=0, le=999)
    version_suffix: str | None = Field(default=None, max_length=64)
    extra_mods_upload_id: str | None = Field(default=None, min_length=8, max_length=64)
    mods_disabled: list[str] | None = None
    debloat_disabled: list[str] | None = None
    debloat_add_system: list[str] | None = None
    debloat_add_product: list[str] | None = None
    force: bool = False
    no_rom_zip: bool = False


class BuildJobRead(BaseModel):
    id: str
    job_kind: str | None = None
    operation_name: str | None = None
    target: str
    source_commit: str
    source_firmware: str | None
    target_firmware: str | None
    version_major: int | None
    version_minor: int | None
    version_patch: int | None
    version_suffix: str | None
    build_signature: str | None
    force: bool
    no_rom_zip: bool
    status: str
    queue_job_id: str | None
    return_code: int | None
    error: str | None
    log_path: str | None
    artifact_path: str | None
    reused_from_job_id: str | None
    extra_mods_modules_json: str | None
    debloat_disabled_json: str | None
    debloat_add_system_json: str | None
    debloat_add_product_json: str | None
    mods_disabled_json: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class StopJobRequest(BaseModel):
    signal_type: str = Field(default="sigterm", pattern="^(sigterm|sigkill)$")


class RepoConfigUpdate(BaseModel):
    git_url: str = Field(min_length=8, max_length=512)
    git_username: str | None = Field(default=None, max_length=128)
    git_token: str | None = Field(default=None, max_length=512)
