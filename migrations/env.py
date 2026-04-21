"""Alembic environment configuration for async asyncpg."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override URL from env if available
url = os.environ.get("BRAINYCAT_DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def run_migrations_offline() -> None:
    """Run migrations in offline mode (generates SQL)."""
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    """Run migrations with a connection."""
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using asyncpg."""
    import asyncpg

    assert url is not None
    # Convert SQLAlchemy URL to asyncpg format
    dsn = url.replace("postgresql://", "postgresql://").replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    # asyncpg doesn't support Alembic directly, so we use raw SQL via the migration files
    # For simplicity, we run offline mode and apply via psql, or use synchronous fallback
    await conn.close()


def run_migrations_online() -> None:
    """Run migrations in online mode using synchronous psycopg2 fallback."""
    # Alembic needs a synchronous connection; we use psycopg2 for migrations only
    from sqlalchemy import create_engine

    assert url is not None
    engine = create_engine(url)
    with engine.connect() as connection:
        do_run_migrations(connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
