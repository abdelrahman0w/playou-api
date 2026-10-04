from fastapi import APIRouter
from fastapi import Depends
from fastapi import Response
from fastapi import status

from src.controllers import playback as playback_controller
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import PlatformsDep
from src.dependencies import SessionFactoryDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.structs.enums import Platforms
from src.structs.models import PlaybackDevice
from src.structs.models.requests import EmbedBlockedRequest
from src.structs.models.requests import PlayRequest
from src.structs.models.requests import RejectedTokenRequest
from src.structs.models.responses import PlaybackToken


router = APIRouter(prefix="/playback")


@router.get("/{platform}/token")
async def playback_token(
    platform: Platforms,
    response: Response,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> PlaybackToken:
    response.headers["Cache-Control"] = "no-store"

    return await playback_controller.playback_token(
        session,
        session_factory,
        platforms,
        platform,
        user_id=user_id,
        now=now,
    )


@router.post(
    "/{platform}/token",
    dependencies=[Depends(require_trusted_origin)],
)
async def refresh_playback_token(
    platform: Platforms,
    request: RejectedTokenRequest,
    response: Response,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> PlaybackToken:
    response.headers["Cache-Control"] = "no-store"

    return await playback_controller.playback_token(
        session,
        session_factory,
        platforms,
        platform,
        user_id=user_id,
        now=now,
        rejected=request.rejected,
    )


@router.get("/{platform}/devices")
async def list_devices(
    platform: Platforms,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> list[PlaybackDevice]:
    return await playback_controller.list_devices(
        session,
        session_factory,
        platforms,
        platform,
        user_id=user_id,
        now=now,
    )


@router.post(
    "/{platform}/play",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def play(
    platform: Platforms,
    body: PlayRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> Response:
    await playback_controller.play(
        session,
        session_factory,
        platforms,
        platform,
        body,
        user_id=user_id,
        now=now,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{platform}/blocked",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def block_embedding(
    platform: Platforms,
    body: EmbedBlockedRequest,
    _user_id: UserIDDep,
    session: DBSessionDep,
    now: NowDep,
) -> Response:
    await playback_controller.block_embedding(session, platform, body, now=now)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
