from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations():
    inspector = inspect(engine)
    if "build_jobs" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("build_jobs")}
    statements = []
    if "source_commit" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN source_commit VARCHAR(64) DEFAULT 'unknown'")
    if "reused_from_job_id" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN reused_from_job_id VARCHAR(36)")
    if "source_firmware" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN source_firmware VARCHAR(128)")
    if "target_firmware" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN target_firmware VARCHAR(128)")
    if "version_major" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN version_major INTEGER")
    if "version_minor" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN version_minor INTEGER")
    if "version_patch" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN version_patch INTEGER")
    if "version_suffix" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN version_suffix VARCHAR(64)")
    if "build_signature" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN build_signature VARCHAR(128)")
    if "process_pid" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN process_pid INTEGER")
    if "job_kind" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN job_kind VARCHAR(32) DEFAULT 'build'")
    if "operation_name" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN operation_name VARCHAR(128)")
    if "extra_mods_archive_path" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN extra_mods_archive_path TEXT")
    if "extra_mods_modules_json" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN extra_mods_modules_json TEXT")
    if "debloat_disabled_json" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN debloat_disabled_json TEXT")
    if "debloat_add_system_json" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN debloat_add_system_json TEXT")
    if "debloat_add_product_json" not in cols:
        statements.append("ALTER TABLE build_jobs ADD COLUMN debloat_add_product_json TEXT")

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        if "build_signature" not in cols:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_build_jobs_build_signature ON build_jobs (build_signature)"))
