import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from shared.repositories._tables import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _db_url() -> str:
    """Return the DB URL, preferring DATABASE_URL env var over alembic.ini.

    Strips async dialect variants (+asyncpg, +aiopg) because Alembic uses a
    sync engine. The app itself keeps the async URL in DATABASE_URL.
    """
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    return url.replace("+asyncpg", "").replace("+aiopg", "")


def run_migrations_offline() -> None:
    url = _db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {**config.get_section(config.config_ini_section, {}), "sqlalchemy.url": _db_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
