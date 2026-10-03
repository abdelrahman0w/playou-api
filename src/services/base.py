from datetime import timedelta
from typing import Protocol

from src.structs.enums import Platforms
from src.structs.models import Capabilities
from src.structs.models import PlatformPlaylist
from src.structs.models import PlatformProfile
from src.structs.models import PlatformTokens
from src.structs.models import RemotePlaylist
from src.structs.models import SavedTracksPage
from src.structs.models import Track


class MusicPlatform(Protocol):
    @property
    def platform(self) -> Platforms: ...

    @property
    def capabilities(self) -> Capabilities: ...

    @property
    def refresh_token_lifetime(self) -> timedelta | None: ...

    @property
    def refresh_extends_lifetime(self) -> bool: ...

    async def search(
        self,
        access_token: str,
        query: str,
        *,
        limit: int,
    ) -> list[Track]: ...

    async def saved_tracks(
        self,
        access_token: str,
        *,
        offset: int,
    ) -> SavedTracksPage: ...

    async def user_playlists(
        self,
        access_token: str,
    ) -> list[RemotePlaylist]: ...

    async def playlist_tracks(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[Track]: ...

    async def save_tracks(
        self,
        access_token: str,
        platform_ids: list[str],
    ) -> None: ...

    async def unsave_tracks(
        self,
        access_token: str,
        platform_ids: list[str],
    ) -> None: ...

    async def create_playlist(
        self,
        access_token: str,
        *,
        name: str,
        description: str | None,
    ) -> PlatformPlaylist: ...

    async def update_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        *,
        name: str,
        description: str | None,
    ) -> None: ...

    async def delete_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> None: ...

    async def playlist_track_ids(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[str]: ...

    async def add_to_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None: ...

    async def remove_from_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None: ...

    async def close(self) -> None: ...


class OAuthPlatform(MusicPlatform, Protocol):
    def authorize_url(
        self,
        *,
        state: str,
        challenge: str,
    ) -> str: ...

    async def exchange_code(
        self,
        code: str,
        *,
        verifier: str,
    ) -> PlatformTokens: ...

    async def refresh(
        self,
        refresh_token: str,
    ) -> PlatformTokens: ...

    async def profile(
        self,
        access_token: str,
    ) -> PlatformProfile: ...
