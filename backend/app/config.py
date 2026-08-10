from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "UN1CA Build API"
    api_prefix: str = "/api/v1"

    redis_url: str = "redis://redis:6379/0"
    database_url: str = "sqlite:////data/app.db"

    # Legacy single-workspace paths. They stay meaningful as the source of the
    # migrated default workspace; every new workspace lives under workspaces_root
    un1ca_root: str = "/workspace"
    out_dir: str = "/workspace/out"

    # Parent directory that holds one sub-directory per workspace
    workspaces_root: str = "/workspace"
    # Sub-directory of workspaces_root that holds the odin/fw cache shared by
    # every workspace with shared_fw_cache enabled
    shared_cache_dirname: str = "_shared"

    data_dir: str = "/data"
    logs_dir: str = "/data/logs"
    source_commit: str = "unknown"
    repo_url_default: str = "https://github.com/salvogiangri/UN1CA.git"
    repo_ref_default: str = "sixteen"

    cors_origins: str = "*"


settings = Settings()
