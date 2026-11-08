import re
import time
from collections.abc import Awaitable
from datetime import timedelta
from typing import NoReturn
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel
from pydantic import SecretStr
from pydantic import ValidationError

from src.exceptions import InvalidOAuthStateError
from src.exceptions import PlatformError
from src.exceptions import PlatformNotFoundError
from src.exceptions import PlatformRateLimitedError
from src.exceptions import PlatformReconnectRequiredError
from src.exceptions import PlatformTimeoutError
from src.exceptions import PlatformTokenRejectedError
from src.exceptions import PlatformUnavailableError
from src.exceptions import UnsupportedError
from src.providers import RedisConnection
from src.services.limits import PlatformPause
from src.services.soundcloud.models import SoundCloudMe
from src.services.soundcloud.models import SoundCloudPlaylist
from src.services.soundcloud.models import SoundCloudPlaylists
from src.services.soundcloud.models import SoundCloudStreams
from src.services.soundcloud.models import SoundCloudToken
from src.services.soundcloud.models import SoundCloudTokenError
from src.services.soundcloud.models import SoundCloudTrack
from src.services.soundcloud.models import SoundCloudTracks
from src.services.youtube.parse import parse_video
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.models import Capabilities
from src.structs.models import PlatformPlaylist
from src.structs.models import PlatformProfile
from src.structs.models import PlatformTokens
from src.structs.models import PlaybackDevice
from src.structs.models import PlaybackRequest
from src.structs.models import PlaylistTracks
from src.structs.models import RemotePlaylist
from src.structs.models import SavedTrack
from src.structs.models import SavedTracksPage
from src.structs.models import Track
from src.utils import Singleton


CAPABILITIES = Capabilities(
    search=True,
    search_on_demand=settings.soundcloud.search_on_demand,
    copy_to=True,
    copy_likes=settings.soundcloud.copy_likes,
    push_by_default=False,
    like=True,
    playlists_read=True,
    playlists_write=True,
    playlist_remove=True,
    stream=True,
)

INVALID_GRANT = "invalid_grant"
PAGE = 200
EVERY_ACCESS = "playable,preview,blocked"
TRACK_URN = re.compile(r"soundcloud:tracks:\d+")

ENDPOINT_GROUPS = (
    ("/me/likes", "likes"),
    ("/likes", "likes"),
    ("/tracks/", "streams"),
    ("/tracks", "search"),
)


def _group(path: str) -> str:
    return next(
        (group for prefix, group in ENDPOINT_GROUPS if path.startswith(prefix)),
        "other",
    )


def _auth(access_token: str) -> dict[str, str]:
    return {"Authorization": f"OAuth {access_token}"}


def _parse[T: BaseModel](response: httpx.Response, shape: type[T]) -> T:
    try:
        return shape.model_validate_json(response.content)
    except ValidationError as exc:
        raise PlatformError("SoundCloud answered something unexpected") from exc


def _check(response: httpx.Response) -> httpx.Response:
    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise PlatformTokenRejectedError("SoundCloud no longer accepts the account")
    if response.status_code == httpx.codes.NOT_FOUND:
        raise PlatformNotFoundError("SoundCloud does not have it anymore")
    if response.is_error:
        raise PlatformError(f"SoundCloud responded with status {response.status_code}")

    return response


def _retry_after(response: httpx.Response) -> int:
    if (seconds := response.headers.get("retry-after", "")).isdigit():
        return max(1, int(seconds))
    if (reset := response.headers.get("x-ratelimit-reset", "")).isdigit():
        return max(1, int(reset) - int(time.time()))

    return settings.soundcloud.rate_limit_seconds


def _to_tokens(token: SoundCloudToken) -> PlatformTokens:
    return PlatformTokens(
        access_token=SecretStr(token.access_token),
        refresh_token=SecretStr(token.refresh_token) if token.refresh_token else None,
        expires_in_seconds=token.expires_in,
        scopes=(token.scope or "").split(),
    )


def _sized(artwork_url: str | None, size: str) -> str | None:
    return artwork_url.replace("-large.", f"-{size}.") if artwork_url else None


def _to_track(track: SoundCloudTrack) -> Track:
    title, artists = parse_video(
        track.title or "Untitled",
        track.metadata_artist or track.user.username or "",
    )

    return Track(
        platform=Platforms.SOUNDCLOUD,
        platform_id=track.urn,
        title=title,
        artists=[artist for artist in artists if artist],
        duration_ms=track.duration,
        isrc=track.isrc,
        artwork_url=_sized(track.artwork_url, "t500x500"),
        thumbnail_url=_sized(track.artwork_url, "t300x300"),
        url=track.permalink_url,
    )


def _snapshot(playlist: SoundCloudPlaylist) -> str:
    return f"{playlist.last_modified}:{playlist.track_count}"


def _to_playlist(playlist: SoundCloudPlaylist) -> RemotePlaylist:
    return RemotePlaylist(
        platform_id=playlist.urn,
        name=playlist.title or "Untitled",
        description=playlist.description or None,
        owner_id=playlist.user.urn,
        owner_name=playlist.user.username,
        snapshot_id=_snapshot(playlist),
        cover_url=_sized(playlist.artwork_url, "t500x500"),
        url=playlist.permalink_url,
    )


def _unsupported(*_: object) -> NoReturn:
    raise UnsupportedError("SoundCloud cannot do that yet")


class SoundCloudService:
    platform = Platforms.SOUNDCLOUD
    capabilities = CAPABILITIES
    scopes: list[str] = []
    playback_scopes: list[str] = []
    refresh_extends_lifetime = False

    def __init__(
        self,
        accounts: httpx.AsyncClient,
        api: httpx.AsyncClient,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        search_max_limit: int = 50,
        refresh_token_lifetime: timedelta | None = None,
        pause: PlatformPause | None = None,
    ) -> None:
        self._accounts = accounts
        self._api = api
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._search_max_limit = search_max_limit
        self.refresh_token_lifetime = refresh_token_lifetime
        self._pause = pause
        if pause is not None:
            api.event_hooks["request"].append(self._paused)

    async def _paused(self, request: httpx.Request) -> None:
        if self._pause is not None:
            await self._pause.check(_group(request.url.path))

    async def _send(
        self,
        request: Awaitable[httpx.Response],
        *,
        pausable: bool = True,
    ) -> httpx.Response:
        pause = self._pause if pausable else None
        try:
            response = await request
        except httpx.TimeoutException as exc:
            raise PlatformTimeoutError("SoundCloud took too long to respond") from exc
        except httpx.RequestError as exc:
            raise PlatformUnavailableError("SoundCloud could not be reached") from exc

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            seconds = _retry_after(response)
            if pause is not None:
                path = response.request.url.path
                raise await pause.pause(seconds, group=_group(path), path=path)

            raise PlatformRateLimitedError(
                f"SoundCloud is limiting the requests, try again in {seconds} seconds",
                retry_after_seconds=seconds,
            )

        return response

    async def _call(self, request: Awaitable[httpx.Response]) -> httpx.Response:
        return _check(await self._send(request))

    def authorize_url(self, *, state: str, challenge: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
            },
        )

        return f"{self._accounts.base_url.join('/authorize')}?{query}"

    async def _token(
        self,
        form: dict[str, str],
    ) -> SoundCloudToken | SoundCloudTokenError:
        response = await self._send(
            self._accounts.post(
                "/oauth/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    **form,
                },
            ),
            pausable=False,
        )
        if response.status_code in {httpx.codes.BAD_REQUEST, httpx.codes.UNAUTHORIZED}:
            return _parse(response, SoundCloudTokenError)
        if response.is_error:
            raise PlatformError(
                f"SoundCloud responded with status {response.status_code}",
            )

        return _parse(response, SoundCloudToken)

    async def exchange_code(self, code: str, *, verifier: str) -> PlatformTokens:
        token = await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": verifier,
            },
        )
        if isinstance(token, SoundCloudTokenError):
            if token.error == INVALID_GRANT:
                raise InvalidOAuthStateError(
                    "The link with SoundCloud expired, start again",
                )

            raise PlatformError(f"SoundCloud refused the link, {token.error}")

        return _to_tokens(token)

    async def refresh(self, refresh_token: str) -> PlatformTokens:
        token = await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": self._redirect_uri,
            },
        )
        if isinstance(token, SoundCloudTokenError):
            if token.error == INVALID_GRANT:
                raise PlatformReconnectRequiredError(
                    "SoundCloud no longer accepts the account, link it again",
                )

            raise PlatformError(f"SoundCloud refused the refresh, {token.error}")

        return _to_tokens(token)

    async def _me(self, access_token: str) -> SoundCloudMe:
        return _parse(
            await self._call(self._api.get("/me", headers=_auth(access_token))),
            SoundCloudMe,
        )

    async def profile(self, access_token: str) -> PlatformProfile:
        me = await self._me(access_token)

        return PlatformProfile(external_id=me.urn, display_name=me.username)

    async def search(
        self,
        access_token: str,
        query: str,
        *,
        limit: int,
    ) -> list[Track]:
        page = _parse(
            await self._call(
                self._api.get(
                    "/tracks",
                    params={
                        "q": query,
                        "limit": min(limit, self._search_max_limit),
                        "access": "playable",
                        "linked_partitioning": "true",
                    },
                    headers=_auth(access_token),
                ),
            ),
            SoundCloudTracks,
        )

        return [_to_track(track) for track in page.collection]

    def _page(
        self,
        access_token: str,
        path: str,
        href: str | None,
        **params: str,
    ) -> Awaitable[httpx.Response]:
        if href is not None:
            return self._api.get(
                httpx.URL(href).raw_path.decode(),
                headers=_auth(access_token),
            )

        return self._api.get(
            path,
            params={"limit": PAGE, "linked_partitioning": "true", **params},
            headers=_auth(access_token),
        )

    async def saved_tracks(
        self,
        access_token: str,
        *,
        cursor: str | None,
    ) -> SavedTracksPage:
        if cursor is None:
            total = (await self._me(access_token)).likes_count or 0
            href = None
        else:
            count, _, href = cursor.partition(":")
            total = int(count)

        page = _parse(
            await self._call(self._page(access_token, "/me/likes/tracks", href)),
            SoundCloudTracks,
        )

        return SavedTracksPage(
            total=total,
            items=[SavedTrack(track=_to_track(track)) for track in page.collection],
            next=f"{total}:{page.next_href}"
            if page.next_href and page.collection
            else None,
        )

    async def user_playlists(self, access_token: str) -> list[RemotePlaylist]:
        playlists: list[RemotePlaylist] = []
        href: str | None = None
        while True:
            page = _parse(
                await self._call(
                    self._page(
                        access_token,
                        "/me/playlists",
                        href,
                        show_tracks="false",
                    ),
                ),
                SoundCloudPlaylists,
            )
            playlists += [_to_playlist(playlist) for playlist in page.collection]
            if not page.next_href or not page.collection:
                return playlists

            href = page.next_href

    async def _playlist_items(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[SoundCloudTrack]:
        tracks: list[SoundCloudTrack] = []
        href: str | None = None
        while True:
            page = _parse(
                await self._call(
                    self._page(
                        access_token,
                        f"/playlists/{platform_playlist_id}/tracks",
                        href,
                        access=EVERY_ACCESS,
                    ),
                ),
                SoundCloudTracks,
            )
            tracks += page.collection
            if not page.next_href or not page.collection:
                return tracks

            href = page.next_href

    async def playlist_tracks(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> PlaylistTracks:
        items = await self._playlist_items(access_token, platform_playlist_id)

        return PlaylistTracks(tracks=[_to_track(track) for track in items])

    async def playlist_track_ids(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[str]:
        items = await self._playlist_items(access_token, platform_playlist_id)

        return [track.urn for track in items]

    async def save_tracks(self, access_token: str, platform_ids: list[str]) -> None:
        for urn in platform_ids:
            await self._call(
                self._api.post(f"/likes/tracks/{urn}", headers=_auth(access_token)),
            )

    async def unsave_tracks(self, access_token: str, platform_ids: list[str]) -> None:
        for urn in platform_ids:
            try:
                await self._call(
                    self._api.delete(
                        f"/likes/tracks/{urn}",
                        headers=_auth(access_token),
                    ),
                )
            except PlatformNotFoundError:
                continue

    async def create_playlist(
        self,
        access_token: str,
        *,
        name: str,
        description: str | None,
    ) -> PlatformPlaylist:
        created = _parse(
            await self._call(
                self._api.post(
                    "/playlists",
                    json={
                        "playlist": {
                            "title": name,
                            "description": description or "",
                            "sharing": "private",
                        },
                    },
                    headers=_auth(access_token),
                ),
            ),
            SoundCloudPlaylist,
        )

        return PlatformPlaylist(
            platform_id=created.urn,
            snapshot_id=_snapshot(created),
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
                json={"playlist": {"title": name, "description": description or ""}},
                headers=_auth(access_token),
            ),
        )

    async def delete_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> None:
        await self._call(
            self._api.delete(
                f"/playlists/{platform_playlist_id}",
                headers=_auth(access_token),
            ),
        )

    async def _whole_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[str]:
        playlist = _parse(
            await self._call(
                self._api.get(
                    f"/playlists/{platform_playlist_id}",
                    params={"show_tracks": "false"},
                    headers=_auth(access_token),
                ),
            ),
            SoundCloudPlaylist,
        )
        urns = await self.playlist_track_ids(access_token, platform_playlist_id)
        if len(urns) < (playlist.track_count or 0):
            raise PlatformError("SoundCloud did not list the whole playlist")

        return urns

    async def _write_tracks(
        self,
        access_token: str,
        platform_playlist_id: str,
        urns: list[str],
    ) -> str:
        return _snapshot(
            _parse(
                await self._call(
                    self._api.put(
                        f"/playlists/{platform_playlist_id}",
                        json={"playlist": {"tracks": [{"urn": urn} for urn in urns]}},
                        headers=_auth(access_token),
                    ),
                ),
                SoundCloudPlaylist,
            ),
        )

    async def add_to_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None:
        current = await self._whole_playlist(access_token, platform_playlist_id)

        return await self._write_tracks(
            access_token,
            platform_playlist_id,
            [*current, *(urn for urn in platform_ids if urn not in current)],
        )

    async def remove_from_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None:
        current = await self._whole_playlist(access_token, platform_playlist_id)
        unwanted = set(platform_ids)

        return await self._write_tracks(
            access_token,
            platform_playlist_id,
            [urn for urn in current if urn not in unwanted],
        )

    async def stream_url(self, access_token: str, platform_id: str) -> str:
        if TRACK_URN.fullmatch(platform_id) is None:
            raise PlatformNotFoundError("SoundCloud has no such track")

        response = await self._send(
            self._api.get(
                f"/tracks/{platform_id}/streams",
                headers=_auth(access_token),
            ),
        )
        if response.status_code == httpx.codes.FORBIDDEN:
            raise PlatformNotFoundError("SoundCloud does not stream this track")

        streams = _parse(_check(response), SoundCloudStreams)
        url = streams.hls_aac_160_url or streams.hls_aac_96_url
        if url is None:
            raise PlatformNotFoundError("SoundCloud only has a preview of this track")

        return url

    async def devices(self, access_token: str) -> list[PlaybackDevice]:
        _unsupported(access_token)

    async def play(self, access_token: str, request: PlaybackRequest) -> None:
        _unsupported(access_token, request)

    async def close(self) -> None:
        await self._accounts.aclose()
        await self._api.aclose()


class SoundCloudConnection(Singleton[SoundCloudService | None]):
    @classmethod
    def create(cls) -> SoundCloudService | None:
        soundcloud = settings.soundcloud
        if not (soundcloud.client_id and soundcloud.client_secret):
            return None

        return SoundCloudService(
            httpx.AsyncClient(
                base_url=soundcloud.accounts_url,
                timeout=soundcloud.timeout_seconds,
            ),
            httpx.AsyncClient(
                base_url=soundcloud.api_url,
                timeout=soundcloud.timeout_seconds,
            ),
            client_id=soundcloud.client_id,
            client_secret=soundcloud.client_secret.get_secret_value(),
            redirect_uri=soundcloud.redirect_uri,
            search_max_limit=soundcloud.search_max_limit,
            refresh_token_lifetime=timedelta(days=soundcloud.refresh_token_days)
            if soundcloud.refresh_token_days
            else None,
            pause=PlatformPause(
                RedisConnection.get(),
                Platforms.SOUNDCLOUD,
                name="SoundCloud",
            ),
        )

    @classmethod
    async def dispose(cls, instance: SoundCloudService | None) -> None:
        if instance is not None:
            await instance.close()
