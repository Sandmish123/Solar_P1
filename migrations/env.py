import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from app.models.solar_project import Base
from app.models.irradiance_cache import IrradianceCache  # noqa: F401  (registers the table)
from app.models.building_cache import BuildingCache  # noqa: F401  (registers the table)

# Alembic Config object
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy metadata
target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Use DATABASE_URL when provided (e.g. Render PostgreSQL).
    Otherwise fall back to sqlalchemy.url from alembic.ini
    (e.g. local SQLite).
    """
    return os.getenv(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    )


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    url = get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    database_url = get_database_url()

    connectable = engine_from_config(
        {
            "sqlalchemy.url": database_url,
        },
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
