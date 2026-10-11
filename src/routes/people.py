from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import Path
from fastapi import Query
from fastapi import Response
from fastapi import status

from src.actions import messages as messages_actions
from src.controllers import people as people_controller
from src.dependencies import ClientIPDep
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import OptionalUserIDDep
from src.dependencies import RedisDep
from src.dependencies import SessionFactoryDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.structs.enums import FollowStates
from src.structs.models import Page
from src.structs.models.requests import PeoplePageRequest
from src.structs.models.requests import PeopleSearchRequest
from src.structs.models.responses import Person
from src.structs.models.responses import Profile
from src.structs.models.responses import ProfilePlaylistSongs
from src.structs.models.responses import UsernameCheck


router = APIRouter(prefix="/people")
writes = [Depends(require_trusted_origin)]
Username = Annotated[str, Path(min_length=1, max_length=40)]
NO_CONTENT = status.HTTP_204_NO_CONTENT


def _done() -> Response:
    return Response(status_code=NO_CONTENT)


@router.get("/search")
async def search(
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    request: Annotated[PeopleSearchRequest, Query()],
) -> list[Person]:
    return await people_controller.search(
        session,
        redis,
        request.q,
        viewer_id=user_id,
    )


@router.get("/usernames/{username}")
async def check_username(
    username: Username,
    user_id: OptionalUserIDDep,
    ip: ClientIPDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> UsernameCheck:
    return await people_controller.check_username(
        session,
        redis,
        username,
        viewer_id=user_id,
        ip=ip,
    )


@router.get("/requests")
async def requests(
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[PeoplePageRequest, Query()],
) -> Page[Person]:
    return await people_controller.requests(session, request, viewer_id=user_id)


async def _answer(
    username: str,
    user_id: UUID,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    background: BackgroundTasks,
    now: NowDep,
    *,
    accept: bool,
) -> Response:
    follower = await people_controller.answer_request(
        session,
        username,
        viewer_id=user_id,
        accept=accept,
        now=now,
    )
    if follower is not None:
        background.add_task(
            messages_actions.notify_follow,
            session_factory,
            kind="accepted",
            actor_id=user_id,
            recipient_id=follower,
        )

    return _done()


@router.post("/requests/{username}/accept", status_code=NO_CONTENT, dependencies=writes)
async def accept_request(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    background: BackgroundTasks,
    now: NowDep,
) -> Response:
    return await _answer(
        username,
        user_id,
        session,
        session_factory,
        background,
        now,
        accept=True,
    )


@router.post(
    "/requests/{username}/decline", status_code=NO_CONTENT, dependencies=writes
)
async def decline_request(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    background: BackgroundTasks,
    now: NowDep,
) -> Response:
    return await _answer(
        username,
        user_id,
        session,
        session_factory,
        background,
        now,
        accept=False,
    )


@router.put(
    "/playlists/{playlist_id}/profile",
    status_code=NO_CONTENT,
    dependencies=writes,
)
async def show_on_profile(
    playlist_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await people_controller.set_on_profile(
        session,
        playlist_id,
        viewer_id=user_id,
        on_profile=True,
    )

    return _done()


@router.delete(
    "/playlists/{playlist_id}/profile",
    status_code=NO_CONTENT,
    dependencies=writes,
)
async def hide_from_profile(
    playlist_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await people_controller.set_on_profile(
        session,
        playlist_id,
        viewer_id=user_id,
        on_profile=False,
    )

    return _done()


@router.get("/{username}")
async def profile(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Profile:
    return await people_controller.profile(session, username, viewer_id=user_id)


@router.get("/{username}/followers")
async def followers(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[PeoplePageRequest, Query()],
) -> Page[Person]:
    return await people_controller.connections(
        session,
        username,
        request,
        viewer_id=user_id,
        followers=True,
    )


@router.get("/{username}/following")
async def following(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[PeoplePageRequest, Query()],
) -> Page[Person]:
    return await people_controller.connections(
        session,
        username,
        request,
        viewer_id=user_id,
        followers=False,
    )


@router.get("/{username}/playlists/{playlist_id}")
async def profile_playlist(
    username: Username,
    playlist_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[PeoplePageRequest, Query()],
) -> ProfilePlaylistSongs:
    return await people_controller.profile_playlist(
        session,
        username,
        playlist_id,
        request,
        viewer_id=user_id,
    )


@router.put("/{username}/follow", dependencies=writes)
async def follow(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    background: BackgroundTasks,
    now: NowDep,
) -> FollowStates:
    state, followed = await people_controller.follow(
        session,
        redis,
        username,
        viewer_id=user_id,
        now=now,
    )
    if followed is not None:
        background.add_task(
            messages_actions.notify_follow,
            session_factory,
            kind="requested" if state == FollowStates.REQUESTED else "followed",
            actor_id=user_id,
            recipient_id=followed,
        )

    return state


@router.delete("/{username}/follow", status_code=NO_CONTENT, dependencies=writes)
async def unfollow(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await people_controller.unfollow(session, username, viewer_id=user_id)

    return _done()


@router.delete("/{username}/follower", status_code=NO_CONTENT, dependencies=writes)
async def remove_follower(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await people_controller.remove_follower(session, username, viewer_id=user_id)

    return _done()


@router.put("/{username}/block", status_code=NO_CONTENT, dependencies=writes)
async def block(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await people_controller.set_blocked(
        session,
        username,
        viewer_id=user_id,
        blocked=True,
    )

    return _done()


@router.delete("/{username}/block", status_code=NO_CONTENT, dependencies=writes)
async def unblock(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await people_controller.set_blocked(
        session,
        username,
        viewer_id=user_id,
        blocked=False,
    )

    return _done()


@router.post("/{username}/report", status_code=NO_CONTENT, dependencies=writes)
async def report(
    username: Username,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await people_controller.report(session, username, viewer_id=user_id)

    return _done()
