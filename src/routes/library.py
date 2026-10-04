from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import Query
from fastapi import Response
from fastapi import status

from src.controllers import library as library_controller
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import PlatformsDep
from src.dependencies import SessionFactoryDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.structs.enums import Platforms
from src.structs.models import Page
from src.structs.models.requests import CreatePlaylistRequest
from src.structs.models.requests import LikeListRequest
from src.structs.models.requests import PlaylistImportingRequest
from src.structs.models.requests import PlaylistItemsRequest
from src.structs.models.requests import PlaylistListRequest
from src.structs.models.requests import UpdatePlaylistRequest
from src.structs.models.responses import AccountSync
from src.structs.models.responses import LikedTrack
from src.structs.models.responses import PlatformData
from src.structs.models.responses import Playlist
from src.structs.models.responses import PlaylistDetail


router = APIRouter(prefix="/library")
writes = [Depends(require_trusted_origin)]


class Pusher:
    def __init__(
        self,
        background: BackgroundTasks,
        session_factory: SessionFactoryDep,
        platforms: PlatformsDep,
        user_id: UserIDDep,
        now: NowDep,
    ) -> None:
        self._background = background
        self._session_factory = session_factory
        self._platforms = platforms
        self._user_id = user_id
        self._now = now

    def push(self) -> None:
        self._background.add_task(
            library_controller.push_changes,
            self._session_factory,
            self._platforms,
            user_id=self._user_id,
            now=self._now,
        )


PusherDep = Annotated[Pusher, Depends()]


class Importer(Pusher):
    def run(self) -> None:
        self._background.add_task(
            library_controller.import_now,
            self._session_factory,
            self._platforms,
            user_id=self._user_id,
            now=self._now,
        )


ImporterDep = Annotated[Importer, Depends()]


@router.get("/likes")
async def list_likes(
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    now: NowDep,
    request: Annotated[LikeListRequest, Query()],
) -> Page[LikedTrack]:
    return await library_controller.list_likes(
        session,
        platforms,
        request,
        user_id=user_id,
        now=now,
    )


@router.put(
    "/likes/{track_id}",
    dependencies=writes,
)
async def like(
    track_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    pusher: PusherDep,
    now: NowDep,
) -> LikedTrack:
    liked = await library_controller.like(
        session,
        platforms,
        track_id,
        user_id=user_id,
        now=now,
    )
    pusher.push()

    return liked


@router.delete(
    "/likes/{track_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def unlike(
    track_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    pusher: PusherDep,
    now: NowDep,
) -> Response:
    await library_controller.unlike(
        session,
        platforms,
        track_id,
        user_id=user_id,
        now=now,
    )
    pusher.push()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.get("/playlists")
async def list_playlists(
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    now: NowDep,
    request: Annotated[PlaylistListRequest, Query()],
) -> Page[Playlist]:
    return await library_controller.list_playlists(
        session,
        platforms,
        request,
        user_id=user_id,
        now=now,
    )


@router.get("/sync")
async def get_sync(
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
) -> list[AccountSync]:
    return await library_controller.get_sync(session, platforms, user_id=user_id)


@router.post("/import", status_code=status.HTTP_202_ACCEPTED, dependencies=writes)
async def request_import(
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    importer: ImporterDep,
    now: NowDep,
) -> list[AccountSync]:
    synced = await library_controller.request_import(
        session,
        platforms,
        user_id=user_id,
        now=now,
    )
    importer.run()

    return synced


@router.post(
    "/playlists",
    status_code=status.HTTP_201_CREATED,
    dependencies=writes,
)
async def create_playlist(
    body: CreatePlaylistRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    pusher: PusherDep,
    now: NowDep,
) -> PlaylistDetail:
    playlist = await library_controller.create_playlist(
        session,
        platforms,
        body,
        user_id=user_id,
        now=now,
    )
    pusher.push()

    return playlist


@router.get("/playlists/{playlist_id}")
async def get_playlist(
    playlist_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    *,
    include_removed: Annotated[bool, Query()] = False,
) -> PlaylistDetail:
    return await library_controller.get_playlist(
        session,
        playlist_id,
        user_id=user_id,
        include_removed=include_removed,
    )


@router.patch(
    "/playlists/{playlist_id}",
    dependencies=writes,
)
async def update_playlist(
    playlist_id: UUID,
    body: UpdatePlaylistRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    pusher: PusherDep,
    now: NowDep,
) -> PlaylistDetail:
    playlist = await library_controller.update_playlist(
        session,
        platforms,
        playlist_id,
        body,
        user_id=user_id,
        now=now,
    )
    pusher.push()

    return playlist


@router.delete(
    "/playlists/{playlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def remove_playlist(
    playlist_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    pusher: PusherDep,
    now: NowDep,
) -> Response:
    await library_controller.remove_playlist(
        session,
        platforms,
        playlist_id,
        user_id=user_id,
        now=now,
    )
    pusher.push()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.put(
    "/playlists/{playlist_id}/importing",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def choose_importing(
    playlist_id: UUID,
    body: PlaylistImportingRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    importer: ImporterDep,
    now: NowDep,
) -> Response:
    await library_controller.choose_importing(
        session,
        platforms,
        playlist_id,
        body,
        user_id=user_id,
        now=now,
    )
    importer.run()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.post(
    "/playlists/{playlist_id}/items",
    dependencies=writes,
)
async def add_playlist_items(
    playlist_id: UUID,
    body: PlaylistItemsRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    pusher: PusherDep,
    now: NowDep,
) -> PlaylistDetail:
    playlist = await library_controller.add_playlist_items(
        session,
        platforms,
        playlist_id,
        body,
        user_id=user_id,
        now=now,
    )
    pusher.push()

    return playlist


@router.delete(
    "/playlists/{playlist_id}/items/{track_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def remove_playlist_item(
    playlist_id: UUID,
    track_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    platforms: PlatformsDep,
    pusher: PusherDep,
    now: NowDep,
) -> Response:
    await library_controller.remove_playlist_item(
        session,
        platforms,
        playlist_id,
        track_id,
        user_id=user_id,
        now=now,
    )
    pusher.push()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.get("/data")
async def get_data(
    user_id: UserIDDep,
    session: DBSessionDep,
) -> list[PlatformData]:
    return await library_controller.get_data(session, user_id=user_id)


@router.delete(
    "/data/{platform}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def remove_platform_data(
    platform: Platforms,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await library_controller.remove_platform_data(session, platform, user_id=user_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/data",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def clear_library(
    user_id: UserIDDep,
    session: DBSessionDep,
    *,
    unlink: bool = True,
) -> Response:
    await library_controller.clear_library(session, user_id=user_id, unlink=unlink)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
