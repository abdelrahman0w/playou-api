import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from src.settings import settings
from src.structs.tables import Base


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# every table is registered on this metadata when `src.structs.tables` is imported
target_metadata = Base.metadata

# an arbitrary id for the advisory lock migrations take, unique to this app
MIGRATIONS_LOCK = 7_529_686

# the database url is read from the settings, not from alembic.ini
database_url = settings.database.url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        # replicas starting together wait their turn, the later ones find nothing to do
        connection.execute(
            text("select pg_advisory_xact_lock(:key)"),
            {"key": MIGRATIONS_LOCK},
        )
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations through the async engine.

    The async engine is used so migrations run on the same
    asyncpg driver as the app, without a second sync driver.

    """
    connectable = create_async_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
