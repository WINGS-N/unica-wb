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
    ff_overrides: dict[str, str | bool] | None = None
    force: bool = False
    no_rom_zip: bool = False
    skip_target_files: bool = False


class BuildJobRead(BaseModel):
    id: str
    workspace_id: str | None = None
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
    skip_target_files: bool
    target_files_path: str | None = None
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
    ff_overrides_json: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class StopJobRequest(BaseModel):
    signal_type: str = Field(default="sigterm", pattern="^(sigterm|sigkill)$")


class RepoConfigUpdate(BaseModel):
    git_url: str = Field(min_length=8, max_length=512)
    git_ref: str | None = Field(default=None, max_length=128)
    git_username: str | None = Field(default=None, max_length=128)
    git_token: str | None = Field(default=None, max_length=512)


class AdvancedSettingsUpdate(BaseModel):
    source_config_override: str | None = Field(default=None, max_length=128)
    targets_override: str | None = Field(default=None, max_length=4096)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    git_url: str = Field(min_length=8, max_length=512)
    git_ref: str | None = Field(default=None, max_length=128)
    git_username: str | None = Field(default=None, max_length=128)
    git_token: str | None = Field(default=None, max_length=512)
    shared_fw_cache: bool = True
    clone_now: bool = True


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    git_url: str | None = Field(default=None, min_length=8, max_length=512)
    git_ref: str | None = Field(default=None, max_length=128)
    git_username: str | None = Field(default=None, max_length=128)
    git_token: str | None = Field(default=None, max_length=512)
    shared_fw_cache: bool | None = None


class PushSubscriptionCreate(BaseModel):
    endpoint: str = Field(min_length=8, max_length=1024)
    keys: dict[str, str]
    language: str | None = Field(default=None, max_length=8)


class PushSubscriptionDelete(BaseModel):
    endpoint: str = Field(min_length=8, max_length=1024)
