from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Request
from fastapi import Response
from fastapi import status

from src.actions import playback as playback_actions
from src.controllers import playback as playback_controller
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import PlatformsDep
from src.dependencies import PlaybackChangesDep
from src.dependencies import RedisDep
from src.dependencies import SessionFactoryDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.models import PlaybackDevice
from src.structs.models.requests import DeviceRequest
from src.structs.models.requests import EmbedBlockedRequest
from src.structs.models.requests import PlaybackPositionRequest
from src.structs.models.requests import PlayRequest
from src.structs.models.requests import RejectedTokenRequest
from src.structs.models.requests import SavePlaybackSessionRequest
from src.structs.models.responses import PlaybackSession
from src.structs.models.responses import PlaybackSessionSaved
from src.structs.models.responses import PlaybackToken


router = APIRouter(prefix="/playback")


@router.get("/session")
async def get_session(
    request: Request,
    response: Response,
    user_id: UserIDDep,
    session: DBSessionDep,
    changes: PlaybackChangesDep,
    wait: Annotated[int, Query(ge=0, le=60)] = 0,
    seen: Annotated[str | None, Query(max_length=100)] = None,
) -> PlaybackSession | None:
    read = await playback_controller.get_session(
        session,
        changes,
        user_id=user_id,
        seen=seen or request.headers.get("if-none-match"),
        wait=min(wait, settings.playback.longest_wait_seconds),
    )
    headers = {"ETag": read.tag, "Cache-Control": "private, no-cache"}
    if read.unchanged:
        return Response(  # type: ignore[return-value]
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    response.headers.update(headers)

    return read.session


@router.put(
    "/session",
    dependencies=[Depends(require_trusted_origin)],
)
async def save_session(
    body: SavePlaybackSessionRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    now: NowDep,
) -> PlaybackSessionSaved:
    saved = await playback_controller.save_session(
        session, body, user_id=user_id, now=now
    )
    await playback_actions.announce(redis, user_id)

    return saved


@router.patch(
    "/session",
    dependencies=[Depends(require_trusted_origin)],
)
async def save_position(
    body: PlaybackPositionRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    now: NowDep,
) -> PlaybackSessionSaved:
    saved = await playback_controller.save_position(
        session, body, user_id=user_id, now=now
    )

    await playback_actions.announce(redis, user_id)

    return saved


@router.post(
    "/session/claim",
    dependencies=[Depends(require_trusted_origin)],
)
async def claim_session(
    body: DeviceRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    now: NowDep,
) -> PlaybackSession:
    claimed = await playback_controller.claim_session(
        session, body, user_id=user_id, now=now
    )
    await playback_actions.announce(redis, user_id)

    return claimed


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def forget_session(
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> Response:
    await playback_controller.forget_session(session, user_id=user_id)
    await playback_actions.announce(redis, user_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
