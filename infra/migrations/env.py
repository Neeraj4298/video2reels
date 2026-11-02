import os
import sys
from pathlib import Path

# Make the project root importable so api.models is resolvable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Load Alembic config
config = context.config

# ── Override DB URL from env var ──────────────────────────────────────────────
db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "+psycopg2")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# ── Logging ───────────────────────────────────────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import all models so Alembic can see them for autogenerate ────────────────
from api.models import Base  # noqa: F401 — registers all ORM models
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
