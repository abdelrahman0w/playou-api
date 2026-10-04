from typing import Annotated

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import Query
from fastapi import Response
from fastapi import status
from fastapi.responses import RedirectResponse

from src.controllers import accounts as accounts_controller
from src.controllers import library as library_controller
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import OptionalUserIDDep
from src.dependencies import PlatformsDep
from src.dependencies import RedisDep
from src.dependencies import SessionFactoryDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.structs.enums import Platforms
from src.structs.models.requests import PushPreferencesRequest
from src.structs.models.responses import LinkedAccount
from src.structs.models.responses import PushPreferences


router = APIRouter(prefix="/accounts")


@router.get("")
async def list_accounts(
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    now: NowDep,
) -> list[LinkedAccount]:
    return await accounts_controller.list_accounts(
        session,
        platforms,
        user_id,
        now=now,
    )


@router.get("/{platform}/connect")
async def connect(
    platform: Platforms,
    user_id: UserIDDep,
    redis: RedisDep,
    platforms: PlatformsDep,
) -> RedirectResponse:
    return RedirectResponse(
        await accounts_controller.connect(
            redis,
            platforms,
            platform,
            user_id=user_id,
        ),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/{platform}/callback")
async def finish_connect(
    platform: Platforms,
    user_id: OptionalUserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    platforms: PlatformsDep,
    session_factory: SessionFactoryDep,
    background: BackgroundTasks,
    now: NowDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    if user_id is not None:
        background.add_task(
            library_controller.import_now,
            session_factory,
            platforms,
            user_id=user_id,
            now=now,
        )

    return RedirectResponse(
        await accounts_controller.finish_connect(
            session,
            redis,
            platforms,
            platform,
            user_id=user_id,
            code=code,
            state=state,
            error=error,
            now=now,
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.delete(
    "/{platform}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def disconnect(
    platform: Platforms,
    user_id: UserIDDep,
    session: DBSessionDep,
    *,
    remove_data: bool = False,
) -> Response:
    await accounts_controller.disconnect(
        session,
        platform,
        user_id=user_id,
        remove_data=remove_data,
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.get("/{platform}/preferences")
async def get_preferences(
    platform: Platforms,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> PushPreferences:
    return await accounts_controller.get_preferences(
        session,
        platform,
        user_id=user_id,
    )


@router.patch(
    "/{platform}/preferences",
    dependencies=[Depends(require_trusted_origin)],
)
async def set_preferences(
    platform: Platforms,
    body: PushPreferencesRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> PushPreferences:
    return await accounts_controller.set_preferences(
        session,
        platform,
        body,
        user_id=user_id,
    )
