from datetime import datetime
from uuid import UUID

from pydantic import TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions.catalog.search import search_platform
from src.exceptions import NotFoundError
from src.providers import logger
from src.repositories import catalog as catalog_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import CacheKeys
from src.structs.enums import Closeness
from src.structs.models import StoredAccount
from src.structs.models import Track
from src.structs.models.requests import SearchRequest
from src.structs.models.responses import Candidate
from src.structs.models.responses import CatalogTrack
from src.utils.matching import closeness
from src.utils.matching import same_song


FIND_LIMIT = 5
CANDIDATE_SEARCH = 10
CANDIDATES = 5
RANKS = list(Closeness)
TRACKS = TypeAdapter(list[Track])


def _query(track: CatalogTrack) -> str:
    return " ".join([track.title, *track.artists[:1]])[:200]


def _song(track: CatalogTrack | Track) -> tuple[str, list[str], int | None]:
    return track.title, list(track.artists), track.duration_ms


async def _search(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    service: OAuthPlatform,
    account: StoredAccount,
    query: str,
    *,
    limit: int,
    now: datetime,
) -> list[Track]:
    return await search_platform(
        session_factory,
        redis,
        service,
        account,
        SearchRequest(q=query, limit=limit),
        now=now,
    )


def _queries(service: OAuthPlatform, track: CatalogTrack) -> list[str]:
    isrc = (
        [f"isrc:{track.isrc}"]
        if track.isrc and service.capabilities.search_isrc
        else []
    )

    return [*isrc, _query(track)]


async def _found(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    service: OAuthPlatform,
    account: StoredAccount,
    track: CatalogTrack,
    *,
    limit: int,
    now: datetime,
) -> list[Track]:
    found: dict[str, Track] = {}
    for query in _queries(service, track):
        for result in await _search(
            session_factory,
            redis,
            service,
            account,
            query,
            limit=limit,
            now=now,
        ):
            found.setdefault(result.platform_id, result)

    return list(found.values())


def _is_match(track: CatalogTrack, result: Track) -> bool:
    if track.isrc and result.isrc:
        return result.isrc == track.isrc

    return same_song(
        _song(track),
        _song(result),
        across_scripts=settings.catalog.match_across_scripts,
    )


async def find_match(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    service: OAuthPlatform,
    account: StoredAccount,
    track: CatalogTrack,
    *,
    now: datetime,
) -> Track | None:
    seen: set[str] = set()
    for query in _queries(service, track):
        for result in await _search(
            session_factory,
            redis,
            service,
            account,
            query,
            limit=FIND_LIMIT,
            now=now,
        ):
            if result.platform_id in seen:
                continue
            seen.add(result.platform_id)
            if _is_match(track, result):
                return result

    return None


async def attach(
    session: AsyncSession,
    track: CatalogTrack,
    found: Track,
) -> UUID:
    (saved,) = await catalog_repositories.save_platform_tracks(session, [found])
    if saved.id == track.id:
        return track.id

    keep, drop = (
        (saved.id, track.id)
        if saved.isrc and not track.isrc
        else (
            track.id,
            saved.id,
        )
    )
    await catalog_repositories.merge_track(session, keep, drop)

    return keep


async def candidates(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    service: OAuthPlatform,
    account: StoredAccount,
    track: CatalogTrack,
    *,
    now: datetime,
) -> list[Candidate]:
    ranked: list[Candidate] = []
    for result in await _found(
        session_factory,
        redis,
        service,
        account,
        track,
        limit=CANDIDATE_SEARCH,
        now=now,
    ):
        hint = (
            Closeness.SAME
            if track.isrc and result.isrc == track.isrc
            else closeness(
                _song(track),
                _song(result),
                across_scripts=settings.catalog.match_across_scripts,
            )
        )
        if hint is not None:
            ranked.append(Candidate(track=result, closeness=hint))

    ranked.sort(key=lambda candidate: RANKS.index(candidate.closeness))
    chosen = ranked[:CANDIDATES]
    try:
        await redis.set(
            CacheKeys.CATALOG_CANDIDATES.format(
                user_id=account.user_id,
                track_id=track.id,
                platform=account.platform,
            ),
            TRACKS.dump_json([candidate.track for candidate in chosen]),
            ex=settings.catalog.candidates_seconds,
        )
    except RedisError:
        logger.warning("[Catalog] Candidates Not Kept - Redis Is Unavailable")

    return chosen


async def chosen_candidate(
    redis: Redis,
    account: StoredAccount,
    track_id: UUID,
    platform_id: str,
) -> Track:
    try:
        kept = await redis.get(
            CacheKeys.CATALOG_CANDIDATES.format(
                user_id=account.user_id,
                track_id=track_id,
                platform=account.platform,
            ),
        )
    except RedisError:
        kept = None

    for candidate in TRACKS.validate_json(kept) if kept else []:
        if candidate.platform_id == platform_id:
            return candidate

    raise NotFoundError("Look for similar songs again")
