from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "UN1CA Build API"
    api_prefix: str = "/api/v1"

    redis_url: str = "redis://redis:6379/0"
    database_url: str = "sqlite:////data/app.db"

    un1ca_root: str = "/workspace"
    out_dir: str = "/workspace/out"

    data_dir: str = "/data"
    logs_dir: str = "/data/logs"
    source_commit: str = "unknown"

    cors_origins: str = "*"


settings = Settings()
