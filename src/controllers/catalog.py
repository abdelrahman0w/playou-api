from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import catalog as catalog_actions
from src.actions import sync as sync_actions
from src.repositories import accounts as accounts_repositories
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.models.requests import ChooseSimilarRequest
from src.structs.models.requests import SearchRequest
from src.structs.models.responses import Candidate
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import SearchResults


async def search(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    request: SearchRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> SearchResults:
    async with session.begin():
        accounts = await accounts_repositories.list_accounts(session, user_id)

    return await catalog_actions.search_tracks(
        session_factory,
        redis,
        platforms,
        accounts,
        request,
        now=now,
    )


async def find_on(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    track_id: UUID,
    platform: Platforms,
    *,
    user_id: UUID,
    now: datetime,
) -> CatalogTrack:
    async with session.begin():
        accounts = await accounts_repositories.list_accounts(session, user_id)

    return await catalog_actions.find_on(
        session_factory,
        redis,
        platforms,
        accounts,
        track_id,
        platform,
        now=now,
    )


async def similar_songs(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    track_id: UUID,
    platform: Platforms,
    *,
    user_id: UUID,
    now: datetime,
) -> list[Candidate]:
    return await sync_actions.similar_songs(
        session_factory,
        redis,
        platforms,
        user_id=user_id,
        track_id=track_id,
        platform=platform,
        now=now,
    )


async def choose_similar(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    track_id: UUID,
    platform: Platforms,
    request: ChooseSimilarRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> CatalogTrack | None:
    return await sync_actions.choose_similar(
        session_factory,
        redis,
        platforms,
        user_id=user_id,
        track_id=track_id,
        platform=platform,
        platform_id=request.platform_id,
        now=now,
    )
