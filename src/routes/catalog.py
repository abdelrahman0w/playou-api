from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query

from src.controllers import catalog as catalog_controller
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import PlatformsDep
from src.dependencies import RedisDep
from src.dependencies import SessionFactoryDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.dependencies import require_user_id
from src.structs.enums import Platforms
from src.structs.models.requests import ChooseSimilarRequest
from src.structs.models.requests import SearchRequest
from src.structs.models.responses import Candidate
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import SearchResults


router = APIRouter(prefix="/catalog")


@router.get("/search")
async def search(
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    platforms: PlatformsDep,
    now: NowDep,
    request: Annotated[SearchRequest, Query()],
) -> SearchResults:
    return await catalog_controller.search(
        session,
        session_factory,
        redis,
        platforms,
        request,
        user_id=user_id,
        now=now,
    )


@router.get(
    "/tracks/{track_id}",
    dependencies=[Depends(require_user_id)],
)
async def get_track(
    track_id: UUID,
    session: DBSessionDep,
) -> CatalogTrack:
    return await catalog_controller.get_track(session, track_id)


@router.post(
    "/tracks/{track_id}/find/{platform}",
    dependencies=[Depends(require_trusted_origin)],
)
async def find_on(
    track_id: UUID,
    platform: Platforms,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> CatalogTrack:
    return await catalog_controller.find_on(
        session,
        session_factory,
        redis,
        platforms,
        track_id,
        platform,
        user_id=user_id,
        now=now,
    )


@router.get("/tracks/{track_id}/similar/{platform}")
async def similar_songs(
    track_id: UUID,
    platform: Platforms,
    user_id: UserIDDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> list[Candidate]:
    return await catalog_controller.similar_songs(
        session_factory,
        redis,
        platforms,
        track_id,
        platform,
        user_id=user_id,
        now=now,
    )


@router.post(
    "/tracks/{track_id}/similar/{platform}",
    dependencies=[Depends(require_trusted_origin)],
)
async def choose_similar(
    track_id: UUID,
    platform: Platforms,
    body: ChooseSimilarRequest,
    user_id: UserIDDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> CatalogTrack | None:
    return await catalog_controller.choose_similar(
        session_factory,
        redis,
        platforms,
        track_id,
        platform,
        body,
        user_id=user_id,
        now=now,
    )
