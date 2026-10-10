from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Path
from fastapi import Query
from fastapi import Response
from fastapi import status

from src.controllers import shares as shares_controller
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import OptionalNamedUserIDDep
from src.dependencies import RedisDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.settings import settings
from src.structs.models import Page
from src.structs.models.requests import ShareListRequest
from src.structs.models.requests import ShareRequest
from src.structs.models.responses import ReceivedShare
from src.structs.models.responses import SentShare
from src.structs.models.responses import SharedTrack
from src.structs.models.responses import ShareLink
from src.structs.models.responses import ShareOpened


router = APIRouter(prefix="/shares")

Code = Annotated[str, Path(min_length=1, max_length=16, pattern=r"^[0-9A-Za-z]+$")]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
async def share(
    request: ShareRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> ShareLink:
    return await shares_controller.share(session, redis, request, user_id=user_id)


@router.get("/sent")
async def list_sent(
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[ShareListRequest, Query()],
) -> Page[SentShare]:
    return await shares_controller.list_sent(session, request, user_id=user_id)


@router.get("/received")
async def list_received(
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[ShareListRequest, Query()],
) -> Page[ReceivedShare]:
    return await shares_controller.list_received(session, request, user_id=user_id)


@router.get("/{code}")
async def read_share(
    code: Code,
    session: DBSessionDep,
    response: Response,
) -> SharedTrack:
    shared = await shares_controller.read_share(session, code)
    response.headers["Cache-Control"] = (
        f"public, max-age={settings.shares.public_cache_seconds}"
    )

    return shared


@router.get(
    "/{code}/image.jpg",
    response_class=Response,
    responses={status.HTTP_200_OK: {"content": {"image/jpeg": {}}}},
)
async def share_image(
    code: Code,
    session: DBSessionDep,
    redis: RedisDep,
) -> Response:
    image = await shares_controller.share_image(session, redis, code)

    return Response(
        content=image,
        media_type="image/jpeg",
        headers={
            "Cache-Control": f"public, max-age={settings.shares.image_max_age_seconds}",
        },
    )


@router.post(
    "/{code}/opens",
    response_model=ShareOpened,
    responses={status.HTTP_204_NO_CONTENT: {"description": "Opened signed out"}},
    dependencies=[Depends(require_trusted_origin)],
)
async def open_share(
    code: Code,
    user_id: OptionalNamedUserIDDep,
    session: DBSessionDep,
    now: NowDep,
) -> ShareOpened | Response:
    opened = await shares_controller.open_share(
        session,
        code,
        user_id=user_id,
        now=now,
    )
    if opened is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return opened


@router.delete(
    "/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def revoke_share(
    code: Code,
    user_id: UserIDDep,
    session: DBSessionDep,
    now: NowDep,
) -> Response:
    await shares_controller.revoke_share(session, code, user_id=user_id, now=now)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
