from collections.abc import Awaitable
from collections.abc import Coroutine
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel
from pydantic import SecretStr
from pydantic import ValidationError

from src.exceptions import InvalidOAuthStateError
from src.exceptions import NoActiveDeviceError
from src.exceptions import PlatformError
from src.exceptions import PlatformNotFoundError
from src.exceptions import PlatformPremiumRequiredError
from src.exceptions import PlatformRateLimitedError
from src.exceptions import PlatformReconnectRequiredError
from src.exceptions import PlatformTimeoutError
from src.exceptions import PlatformTokenRejectedError
from src.exceptions import PlatformUnavailableError
from src.providers import RedisConnection
from src.services.limits import PlatformPause
from src.services.spotify.models import SpotifyDevices
from src.services.spotify.models import SpotifyError
from src.services.spotify.models import SpotifyErrorDetail
from src.services.spotify.models import SpotifyPlaylist
from src.services.spotify.models import SpotifyPlaylistItems
from src.services.spotify.models import SpotifyPlaylistTracks
from src.services.spotify.models import SpotifySavedTracks
from src.services.spotify.models import SpotifySearch
from src.services.spotify.models import SpotifySnapshot
from src.services.spotify.models import SpotifyToken
from src.services.spotify.models import SpotifyTokenError
from src.services.spotify.models import SpotifyTrack
from src.services.spotify.models import SpotifyUser
from src.services.spotify.models import SpotifyUserPlaylists
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.models import Capabilities
from src.structs.models import PlatformPlaylist
from src.structs.models import PlatformProfile
from src.structs.models import PlatformTokens
from src.structs.models import PlaybackDevice
from src.structs.models import PlaybackRequest
from src.structs.models import RemotePlaylist
from src.structs.models import SavedTrack
from src.structs.models import SavedTracksPage
from src.structs.models import Track
from src.utils import Singleton


CAPABILITIES = Capabilities(
    search=True,
    like=True,
    playlists_read=True,
    playlists_write=True,
    playlist_remove=True,
    playback=True,
)

INVALID_GRANT = "invalid_grant"
PREMIUM_REQUIRED = "PREMIUM_REQUIRED"
PLAYBACK_SCOPES = [
    "streaming",
    "user-read-playback-state",
    "user-modify-playback-state",
]

LIBRARY_BATCH = 40
PLAYLIST_BATCH = 100
PLAYLIST_PAGE = 50
LIBRARY_PAGE = 50


def _chunks[T](
    items: list[T],
    size: int,
) -> list[list[T]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def _track_uri(platform_id: str) -> str:
    return f"spotify:track:{platform_id}"


def _check(
    response: httpx.Response,
) -> httpx.Response:
    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise PlatformTokenRejectedError("Spotify no longer accepts the account")
    if response.status_code == httpx.codes.NOT_FOUND:
        raise PlatformNotFoundError("Spotify does not have it anymore")
    if response.is_error:
        raise PlatformError(
            f"Spotify responded with status {response.status_code}"
            + (f", {message}" if (message := _message(response)) else ""),
        )

    return response


def _error(response: httpx.Response) -> SpotifyErrorDetail | None:
    try:
        return SpotifyError.model_validate_json(response.content).error
    except ValidationError:
        return None


def _reason(response: httpx.Response) -> str | None:
    error = _error(response)

    return error.reason if error else None


def _message(response: httpx.Response) -> str | None:
    error = _error(response)

    return error.message if error else None


def _retry_after(response: httpx.Response) -> int:
    try:
        return max(1, int(response.headers.get("retry-after", "")))
    except ValueError:
        return settings.spotify.rate_limit_seconds


def _parse[T: BaseModel](
    response: httpx.Response,
    shape: type[T],
) -> T:
    try:
        return shape.model_validate_json(response.content)
    except ValidationError as exc:
        raise PlatformError("Spotify returned an unexpected response") from exc


def _to_tokens(
    token: SpotifyToken,
) -> PlatformTokens:
    return PlatformTokens(
        access_token=SecretStr(token.access_token),
        refresh_token=SecretStr(token.refresh_token) if token.refresh_token else None,
        expires_in_seconds=token.expires_in,
        refresh_expires_in_seconds=token.refresh_token_expires_in,
        scopes=token.scope.split(),
    )


def _to_track(
    track: SpotifyTrack,
) -> Track:
    album = track.album

    return Track(
        platform=Platforms.SPOTIFY,
        platform_id=track.id,
        title=track.name or "Untitled",
        artists=[artist.name for artist in track.artists if artist.name],
        album=album.name if album else None,
        duration_ms=track.duration_ms,
        isrc=track.external_ids.isrc,
        explicit=track.explicit,
        artwork_url=album.images[0].url if album and album.images else None,
        url=track.external_urls.spotify,
    )


class SpotifyService:
    platform = Platforms.SPOTIFY
    capabilities = CAPABILITIES
    playback_scopes = PLAYBACK_SCOPES
    refresh_extends_lifetime = False

    def __init__(
        self,
        accounts: httpx.AsyncClient,
        api: httpx.AsyncClient,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: list[str],
        search_max_limit: int = 10,
        refresh_token_lifetime: timedelta | None = None,
        pause: PlatformPause | None = None,
    ) -> None:
        self._accounts = accounts
        self._api = api
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self.scopes = scopes
        self._search_max_limit = search_max_limit
        self.refresh_token_lifetime = refresh_token_lifetime
        self._pause = pause

    async def _send(
        self,
        request: Awaitable[httpx.Response],
    ) -> httpx.Response:
        if self._pause is not None:
            try:
                await self._pause.check()
            except PlatformRateLimitedError:
                if isinstance(request, Coroutine):
                    request.close()

                raise

        try:
            response = await request
        except httpx.TimeoutException as exc:
            raise PlatformTimeoutError("Spotify took too long to respond") from exc
        except httpx.RequestError as exc:
            raise PlatformUnavailableError("Spotify could not be reached") from exc

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            seconds = _retry_after(response)
            if self._pause is not None:
                raise await self._pause.pause(seconds)

            raise PlatformRateLimitedError(
                f"Spotify is limiting the requests, try again in {seconds} seconds",
                retry_after_seconds=seconds,
            )

        return response

    async def _call(
        self,
        request: Awaitable[httpx.Response],
    ) -> httpx.Response:
        return _check(await self._send(request))

    def authorize_url(
        self,
        *,
        state: str,
        challenge: str,
    ) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
                "scope": " ".join(self.scopes),
            },
        )

        return f"{self._accounts.base_url.join('/authorize')}?{query}"

    async def _token(self, form: dict[str, str]) -> SpotifyToken | SpotifyTokenError:
        response = await self._send(
            self._accounts.post(
                "/api/token",
                data={"client_id": self._client_id, **form},
            ),
        )
        if response.status_code == httpx.codes.BAD_REQUEST:
            return _parse(response, SpotifyTokenError)

        return _parse(_check(response), SpotifyToken)

    async def exchange_code(
        self,
        code: str,
        *,
        verifier: str,
    ) -> PlatformTokens:
        token = await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": verifier,
            },
        )
        if isinstance(token, SpotifyTokenError):
            if token.error == INVALID_GRANT:
                raise InvalidOAuthStateError(
                    "The link with Spotify expired, start again"
                )

            raise PlatformError(
                f"Spotify refused the link, {token.error}",
            )

        return _to_tokens(token)

    async def refresh(
        self,
        refresh_token: str,
    ) -> PlatformTokens:
        token = await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if isinstance(token, SpotifyTokenError):
            if token.error == INVALID_GRANT:
                raise PlatformReconnectRequiredError(
                    "Spotify no longer accepts the account, link it again",
                )

            raise PlatformError(
                f"Spotify refused the refresh, {token.error}",
            )

        return _to_tokens(token)

    async def profile(
        self,
        access_token: str,
    ) -> PlatformProfile:
        response = await self._call(
            self._api.get("/me", headers=_bearer(access_token)),
        )
        user = _parse(response, SpotifyUser)

        return PlatformProfile(
            external_id=user.id,
            display_name=user.display_name,
        )

    async def search(
        self,
        access_token: str,
        query: str,
        *,
        limit: int,
    ) -> list[Track]:
        response = await self._call(
            self._api.get(
                "/search",
                params={
                    "q": query,
                    "type": "track",
                    "limit": min(limit, self._search_max_limit),
                    "market": "from_token",
                },
                headers=_bearer(access_token),
            ),
        )
        page = _parse(response, SpotifySearch).tracks

        return [_to_track(track) for track in page.items if track is not None]

    async def saved_tracks(
        self,
        access_token: str,
        *,
        cursor: str | None,
    ) -> SavedTracksPage:
        offset = int(cursor or 0)
        response = await self._call(
            self._api.get(
                "/me/tracks",
                params={
                    "limit": LIBRARY_PAGE,
                    "offset": offset,
                    "market": "from_token",
                },
                headers=_bearer(access_token),
            ),
        )
        page = _parse(response, SpotifySavedTracks)

        items = [
            SavedTrack(track=_to_track(saved.track), added_at=saved.added_at)
            for saved in page.items
            if saved.track is not None
        ]
        more = page.next is not None and bool(page.items)

        return SavedTracksPage(
            total=page.total,
            items=items,
            next=str(offset + len(page.items)) if more else None,
        )

    async def user_playlists(
        self,
        access_token: str,
    ) -> list[RemotePlaylist]:
        playlists: list[RemotePlaylist] = []
        offset = 0

        while True:
            response = await self._call(
                self._api.get(
                    "/me/playlists",
                    params={"limit": PLAYLIST_PAGE, "offset": offset},
                    headers=_bearer(access_token),
                ),
            )
            page = _parse(response, SpotifyUserPlaylists)
            playlists.extend(
                RemotePlaylist(
                    platform_id=playlist.id,
                    name=playlist.name,
                    description=playlist.description or None,
                    owner_id=playlist.owner.id,
                    owner_name=playlist.owner.display_name,
                    collaborative=playlist.collaborative,
                    snapshot_id=playlist.snapshot_id,
                    cover_url=playlist.images[0].url if playlist.images else None,
                    url=playlist.external_urls.spotify,
                )
                for playlist in page.items
                if playlist is not None
            )

            if page.next is None or not page.items:
                return playlists

            offset += len(page.items)

    async def playlist_tracks(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[Track]:
        tracks: list[Track] = []
        offset = 0

        while True:
            response = await self._call(
                self._api.get(
                    f"/playlists/{platform_playlist_id}/items",
                    params={
                        "limit": PLAYLIST_PAGE,
                        "offset": offset,
                        "market": "from_token",
                        "additional_types": "track",
                    },
                    headers=_bearer(access_token),
                ),
            )
            page = _parse(response, SpotifyPlaylistTracks)
            tracks.extend(
                _to_track(entry.item)
                for entry in page.items
                if entry.item is not None
                and entry.item.type == "track"
                and not entry.is_local
            )

            if page.next is None or not page.items:
                return tracks

            offset += len(page.items)

    async def _library(
        self,
        method: str,
        access_token: str,
        uris: list[str],
    ) -> None:
        for chunk in _chunks(uris, LIBRARY_BATCH):
            await self._call(
                self._api.request(
                    method,
                    "/me/library",
                    params={"uris": ",".join(chunk)},
                    headers=_bearer(access_token),
                ),
            )

    async def save_tracks(
        self,
        access_token: str,
        platform_ids: list[str],
    ) -> None:
        await self._library(
            "PUT",
            access_token,
            [_track_uri(platform_id) for platform_id in platform_ids],
        )

    async def unsave_tracks(
        self,
        access_token: str,
        platform_ids: list[str],
    ) -> None:
        await self._library(
            "DELETE",
            access_token,
            [_track_uri(platform_id) for platform_id in platform_ids],
        )

    async def create_playlist(
        self,
        access_token: str,
        *,
        name: str,
        description: str | None,
    ) -> PlatformPlaylist:
        response = await self._call(
            self._api.post(
                "/me/playlists",
                json={
                    "name": name,
                    "description": description or "",
                    "public": False,
                },
                headers=_bearer(access_token),
            ),
        )
        playlist = _parse(response, SpotifyPlaylist)

        return PlatformPlaylist(
            platform_id=playlist.id,
            snapshot_id=playlist.snapshot_id,
        )

    async def update_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        *,
        name: str,
        description: str | None,
    ) -> None:
        await self._call(
            self._api.put(
                f"/playlists/{platform_playlist_id}",
                json={
                    "name": name,
                    "description": description or "",
                },
                headers=_bearer(access_token),
            ),
        )

    async def delete_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> None:
        await self._library(
            "DELETE",
            access_token,
            [f"spotify:playlist:{platform_playlist_id}"],
        )

    async def playlist_track_ids(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[str]:
        ids: list[str] = []
        offset = 0

        while True:
            response = await self._call(
                self._api.get(
                    f"/playlists/{platform_playlist_id}/items",
                    params={
                        "fields": "items(is_local,item(id,type)),next",
                        "limit": PLAYLIST_PAGE,
                        "offset": offset,
                    },
                    headers=_bearer(access_token),
                ),
            )
            page = _parse(response, SpotifyPlaylistItems)
            ids.extend(
                entry.item.id
                for entry in page.items
                if entry.item is not None
                and entry.item.type == "track"
                and entry.item.id is not None
                and not entry.is_local
            )

            if page.next is None or not page.items:
                return ids

            offset += len(page.items)

    async def add_to_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None:
        snapshot: str | None = None

        for chunk in _chunks(platform_ids, PLAYLIST_BATCH):
            response = await self._call(
                self._api.post(
                    f"/playlists/{platform_playlist_id}/items",
                    json={
                        "uris": [_track_uri(platform_id) for platform_id in chunk],
                    },
                    headers=_bearer(access_token),
                ),
            )
            snapshot = _parse(response, SpotifySnapshot).snapshot_id

        return snapshot

    async def remove_from_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None:
        snapshot: str | None = None

        for chunk in _chunks(platform_ids, PLAYLIST_BATCH):
            response = await self._call(
                self._api.request(
                    "DELETE",
                    f"/playlists/{platform_playlist_id}/items",
                    json={
                        "items": [
                            {"uri": _track_uri(platform_id)} for platform_id in chunk
                        ],
                    },
                    headers=_bearer(access_token),
                ),
            )
            snapshot = _parse(response, SpotifySnapshot).snapshot_id

        return snapshot

    async def devices(
        self,
        access_token: str,
    ) -> list[PlaybackDevice]:
        response = await self._call(
            self._api.get("/me/player/devices", headers=_bearer(access_token)),
        )

        return [
            PlaybackDevice(
                id=device.id,
                name=device.name,
                type=device.type,
                is_active=device.is_active,
                is_restricted=device.is_restricted,
                volume_percent=device.volume_percent,
            )
            for device in _parse(response, SpotifyDevices).devices
            if device.id is not None
        ]

    async def play(
        self,
        access_token: str,
        request: PlaybackRequest,
    ) -> None:
        body: dict[str, object] = {"position_ms": request.position_ms}
        if request.playlist_id is not None:
            body["context_uri"] = f"spotify:playlist:{request.playlist_id}"
        else:
            body["uris"] = [_track_uri(track_id) for track_id in request.track_ids]
        if request.offset_track_id is not None:
            body["offset"] = {"uri": _track_uri(request.offset_track_id)}

        response = await self._send(
            self._api.put(
                "/me/player/play",
                params={"device_id": request.device_id} if request.device_id else None,
                json=body,
                headers=_bearer(access_token),
            ),
        )
        if response.status_code == httpx.codes.FORBIDDEN:
            if _reason(response) == PREMIUM_REQUIRED:
                raise PlatformPremiumRequiredError("Spotify only plays for Premium")
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NoActiveDeviceError("Spotify has no device to play on, open it first")

        _check(response)

    async def close(self) -> None:
        await self._accounts.aclose()
        await self._api.aclose()


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


class SpotifyConnection(Singleton[SpotifyService | None]):
    @classmethod
    def create(cls) -> SpotifyService | None:
        spotify = settings.spotify
        if not spotify.client_id:
            return None

        return SpotifyService(
            httpx.AsyncClient(
                base_url=spotify.accounts_url,
                timeout=spotify.timeout_seconds,
            ),
            httpx.AsyncClient(
                base_url=spotify.api_url,
                timeout=spotify.timeout_seconds,
            ),
            client_id=spotify.client_id,
            redirect_uri=spotify.redirect_uri,
            scopes=spotify.scopes,
            search_max_limit=spotify.search_max_limit,
            refresh_token_lifetime=timedelta(days=spotify.refresh_token_days)
            if spotify.refresh_token_days
            else None,
            pause=PlatformPause(
                RedisConnection.get(),
                Platforms.SPOTIFY,
                name="Spotify",
            ),
        )

    @classmethod
    async def dispose(cls, instance: SpotifyService | None) -> None:
        if instance is not None:
            await instance.close()
