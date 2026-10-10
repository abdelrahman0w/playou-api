from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import catalog as catalog_actions
from src.actions import sync as sync_actions
from src.exceptions import NotFoundError
from src.repositories import accounts as accounts_repositories
from src.repositories import catalog as catalog_repositories
from src.services import LrclibService
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.models.requests import ChooseSimilarRequest
from src.structs.models.requests import SearchRequest
from src.structs.models.responses import Candidate
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import Lyrics
from src.structs.models.responses import SearchResults


async def get_track(session: AsyncSession, track_id: UUID) -> CatalogTrack:
    async with session.begin():
        tracks = await catalog_repositories.get_tracks(session, [track_id])
    if track_id not in tracks:
        raise NotFoundError("The track does not exist")

    return tracks[track_id]


async def track_lyrics(
    session_factory: async_sessionmaker[AsyncSession],
    lrclib: LrclibService | None,
    track_id: UUID,
    *,
    now: datetime,
) -> Lyrics:
    return await catalog_actions.track_lyrics(
        session_factory,
        lrclib,
        track_id,
        now=now,
    )


async def report_lyrics(
    session: AsyncSession,
    redis: Redis,
    lrclib: LrclibService | None,
    track_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        await catalog_actions.report_lyrics(
            session,
            redis,
            lrclib,
            track_id,
            user_id=user_id,
            now=now,
        )


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
