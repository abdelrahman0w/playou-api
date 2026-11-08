from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

from src.settings import settings
from src.utils import Singleton


def _ms(seconds: float) -> str:
    return str(round(seconds * 1000))


class DatabaseConnection(Singleton[AsyncEngine]):
    @classmethod
    def create(cls) -> AsyncEngine:
        database = settings.database

        return create_async_engine(
            database.url,
            pool_size=database.pool_size,
            max_overflow=database.max_overflow,
            pool_timeout=database.pool_timeout_seconds,
            pool_recycle=database.pool_recycle_seconds,
            pool_pre_ping=database.pool_pre_ping,
            connect_args={
                "server_settings": {
                    "statement_timeout": _ms(database.statement_timeout_seconds),
                    "lock_timeout": _ms(database.lock_timeout_seconds),
                    "idle_in_transaction_session_timeout": _ms(
                        database.idle_in_transaction_timeout_seconds,
                    ),
                },
            },
        )

    @classmethod
    async def connect(cls, instance: AsyncEngine) -> None:
        async with instance.connect() as connection:
            await connection.execute(text("select 1"))

    @classmethod
    async def dispose(cls, instance: AsyncEngine) -> None:
        await instance.dispose()


class DatabaseSessions(Singleton[async_sessionmaker[AsyncSession]]):
    @classmethod
    def create(cls) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            DatabaseConnection.get(),
            expire_on_commit=False,
        )
