from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

from src.settings import settings
from src.utils import Singleton


class DatabaseConnection(Singleton[AsyncEngine]):
    @classmethod
    def create(cls) -> AsyncEngine:
        return create_async_engine(
            settings.database.url,
            pool_pre_ping=True,
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
