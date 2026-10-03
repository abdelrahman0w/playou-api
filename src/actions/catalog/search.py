import asyncio
from datetime import datetime

from pydantic import TypeAdapter
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import accounts as accounts_actions
from src.actions.cache import cached_json
from src.exceptions import PlatformError
from src.exceptions import PlatformReconnectRequiredError
from src.providers import logger
from src.repositories import catalog as catalog_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import AccountStatuses
from src.structs.enums import CacheKeys
from src.structs.enums import Platforms
from src.structs.enums import SearchStatuses
from src.structs.models import StoredAccount
from src.structs.models import Track
from src.structs.models.requests import SearchRequest
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import PlatformSearchResult
from src.structs.models.responses import SearchResults
from src.utils import params_key


TRACKS = TypeAdapter(list[Track])


async def _search_platform(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platform: OAuthPlatform,
    account: StoredAccount,
    request: SearchRequest,
    *,
    now: datetime,
) -> list[Track]:
    async def produce() -> list[Track]:
        token = await accounts_actions.access_token(
            session_factory,
            platform,
            account,
            now=now,
        )

        return await platform.search(
            token,
            request.q,
            limit=request.limit,
        )

    body = await cached_json(
        redis,
        params_key(
            CacheKeys.CATALOG_SEARCH.format(
                platform=account.platform,
                account_id=account.id,
            ),
            request,
        ),
        produce,
        list[Track],
        ttl_seconds=settings.search.cache_seconds,
    )

    return TRACKS.validate_json(body)


async def _search_one(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platform: OAuthPlatform,
    account: StoredAccount,
    request: SearchRequest,
    *,
    now: datetime,
) -> PlatformSearchResult:
    def result(
        status: SearchStatuses,
        tracks: list[CatalogTrack] | None = None,
    ) -> PlatformSearchResult:
        return PlatformSearchResult(
            platform=account.platform,
            status=status,
            tracks=tracks or [],
        )

    if account.status is AccountStatuses.NEEDS_RECONNECT:
        return result(SearchStatuses.NEEDS_RECONNECT)

    try:
        async with asyncio.timeout(settings.search.platform_timeout_seconds):
            tracks = await _search_platform(
                session_factory,
                redis,
                platform,
                account,
                request,
                now=now,
            )
    except TimeoutError:
        logger.warning(
            "[Search] Platform Timed Out",
            platform=account.platform,
        )

        return result(SearchStatuses.TIMED_OUT)
    except PlatformReconnectRequiredError:
        return result(SearchStatuses.NEEDS_RECONNECT)
    except PlatformError as error:
        logger.warning(
            "[Search] Platform Failed",
            platform=account.platform,
            error=error.message,
        )

        return result(SearchStatuses.FAILED)

    async with session_factory() as session, session.begin():
        saved = await catalog_repositories.save_platform_tracks(session, tracks)

    return result(SearchStatuses.OK, saved)


async def search_tracks(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    accounts: list[StoredAccount],
    request: SearchRequest,
    *,
    now: datetime,
) -> SearchResults:
    searched = [
        (platforms[account.platform], account)
        for account in accounts
        if account.platform in platforms
    ]
    results = await asyncio.gather(
        *(
            _search_one(
                session_factory,
                redis,
                platform,
                account,
                request,
                now=now,
            )
            for platform, account in searched
        ),
    )

    return SearchResults(
        query=request.q,
        platforms=list(results),
    )
