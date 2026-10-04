from collections.abc import Awaitable
from collections.abc import Coroutine
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
from src.services.limits import Quota
from src.services.youtube.models import Channels
from src.services.youtube.models import ErrorEnvelope
from src.services.youtube.models import GoogleToken
from src.services.youtube.models import GoogleTokenError
from src.services.youtube.models import GoogleUser
from src.services.youtube.models import Playlist
from src.services.youtube.models import PlaylistItem
from src.services.youtube.models import PlaylistItems
from src.services.youtube.models import Playlists
from src.services.youtube.models import SearchPage
from src.services.youtube.models import Video
from src.services.youtube.models import Videos
from src.services.youtube.parse import duration_ms
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


INVALID_GRANT = "invalid_grant"
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}
MUSIC_CATEGORY = "10"
MUSIC_SHARE = 0.5
LIKED_MUSIC = "LM"
SEARCH_LIMIT = 10
SEARCH_COST = 100
READ_COST = 1
WRITE_COST = 50
PAGE = 50
THUMBNAILS = ("maxres", "high", "medium", "default")


CAPABILITIES = Capabilities(
    search=True,
    search_on_demand=settings.youtube.search_on_demand,
    search_shared=True,
    like=True,
    playlists_read=True,
    playlists_write=True,
    playlist_remove=True,
    push_by_default=False,
    copy_to=True,
    copy_likes=settings.youtube.copy_likes,
    find_cost=SEARCH_COST + READ_COST,
    write_cost=WRITE_COST,
    daily_find_units=settings.youtube.daily_find_units,
    daily_write_units=settings.youtube.daily_push_units,
)


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _parse[T: BaseModel](response: httpx.Response, shape: type[T]) -> T:
    try:
        return shape.model_validate_json(response.content)
    except ValidationError as exc:
        raise PlatformError("YouTube answered something unexpected") from exc


def _reasons(response: httpx.Response) -> set[str]:
    try:
        envelope = ErrorEnvelope.model_validate_json(response.content)
    except ValidationError:
        return set()

    return {error.reason for error in envelope.error.errors if error.reason}


def _to_tokens(token: GoogleToken) -> PlatformTokens:
    return PlatformTokens(
        access_token=SecretStr(token.access_token),
        refresh_token=SecretStr(token.refresh_token) if token.refresh_token else None,
        expires_in_seconds=token.expires_in,
        refresh_expires_in_seconds=token.refresh_token_expires_in,
        scopes=token.scope.split(),
    )


def _to_track(video: Video) -> Track:
    title, artists = parse_video(video.snippet.title, video.snippet.channel_title)
    thumbnails = video.snippet.thumbnails
    artwork = next(
        (thumbnails[size].url for size in THUMBNAILS if size in thumbnails),
        None,
    )

    return Track(
        platform=Platforms.YOUTUBE,
        platform_id=video.id,
        title=title,
        artists=artists,
        duration_ms=duration_ms(video.content_details.duration),
        artwork_url=artwork,
        url=f"https://music.youtube.com/watch?v={video.id}",
    )


def _to_playlist(playlist: Playlist) -> RemotePlaylist:
    thumbnails = playlist.snippet.thumbnails

    return RemotePlaylist(
        platform_id=playlist.id,
        name=playlist.snippet.title,
        description=playlist.snippet.description or None,
        owner_id=playlist.snippet.channel_id,
        owner_name=playlist.snippet.channel_title,
        owned=True,
        snapshot_id=playlist.etag,
        cover_url=next(
            (thumbnails[size].url for size in THUMBNAILS if size in thumbnails),
            None,
        ),
        url=f"https://music.youtube.com/playlist?list={playlist.id}",
    )


def _unsupported(*_: object) -> NoReturn:
    raise UnsupportedError("YouTube Music cannot do that yet")


class YouTubeService:
    platform = Platforms.YOUTUBE
    capabilities = CAPABILITIES
    playback_scopes: list[str] = []
    refresh_extends_lifetime = False

    def __init__(
        self,
        accounts: httpx.AsyncClient,
        token: httpx.AsyncClient,
        userinfo: httpx.AsyncClient,
        api: httpx.AsyncClient,
        *,
        client_id: str,
        client_secret: str,
        api_key: str,
        redirect_uri: str,
        scopes: list[str],
        quota: Quota,
        refresh_token_lifetime: timedelta | None = None,
        pause: PlatformPause | None = None,
    ) -> None:
        self._accounts = accounts
        self._token_client = token
        self._userinfo = userinfo
        self._api = api
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_key = api_key
        self._redirect_uri = redirect_uri
        self.scopes = scopes
        self._quota = quota
        self.refresh_token_lifetime = refresh_token_lifetime
        self._pause = pause

    async def _send(self, request: Awaitable[httpx.Response]) -> httpx.Response:
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
            raise PlatformTimeoutError("YouTube took too long to respond") from exc
        except httpx.RequestError as exc:
            raise PlatformUnavailableError("YouTube could not be reached") from exc

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            seconds = settings.youtube.rate_limit_seconds
            if self._pause is not None:
                raise await self._pause.pause(seconds)

            raise PlatformRateLimitedError(
                f"YouTube is limiting the requests, try again in {seconds} seconds",
                retry_after_seconds=seconds,
            )

        return response

    async def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise PlatformTokenRejectedError("YouTube no longer accepts the account")
        if response.status_code == httpx.codes.NOT_FOUND:
            raise PlatformNotFoundError("YouTube does not have it anymore")
        if (
            response.status_code == httpx.codes.FORBIDDEN
            and _reasons(response) & QUOTA_REASONS
        ):
            raise await self._quota.spend()
        if response.is_error:
            raise PlatformError(f"YouTube responded with status {response.status_code}")

        return response

    async def _call(self, request: Awaitable[httpx.Response]) -> httpx.Response:
        return await self._check(await self._send(request))

    def authorize_url(self, *, state: str, challenge: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri,
                "scope": " ".join(self.scopes),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
            },
        )

        return f"{self._accounts.base_url.join('/o/oauth2/v2/auth')}?{query}"

    async def _token(self, form: dict[str, str]) -> GoogleToken | GoogleTokenError:
        response = await self._send(
            self._token_client.post(
                "/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    **form,
                },
            ),
        )
        if response.status_code in {httpx.codes.BAD_REQUEST, httpx.codes.UNAUTHORIZED}:
            return _parse(response, GoogleTokenError)
        if response.is_error:
            raise PlatformError(f"Google responded with status {response.status_code}")

        return _parse(response, GoogleToken)

    async def exchange_code(self, code: str, *, verifier: str) -> PlatformTokens:
        token = await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": verifier,
            },
        )
        if isinstance(token, GoogleTokenError):
            if token.error == INVALID_GRANT:
                raise InvalidOAuthStateError(
                    "The link with YouTube expired, start again"
                )

            raise PlatformError(f"YouTube refused the link, {token.error}")

        return _to_tokens(token)

    async def refresh(self, refresh_token: str) -> PlatformTokens:
        token = await self._token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        if isinstance(token, GoogleTokenError):
            if token.error == INVALID_GRANT:
                raise PlatformReconnectRequiredError(
                    "YouTube no longer accepts the account, link it again",
                )

            raise PlatformError(f"YouTube refused the refresh, {token.error}")

        return _to_tokens(token)

    async def profile(self, access_token: str) -> PlatformProfile:
        user = _parse(
            await self._call(
                self._userinfo.get("/userinfo", headers=_bearer(access_token))
            ),
            GoogleUser,
        )
        await self._quota.reserve(READ_COST)
        channels = _parse(
            await self._call(
                self._api.get(
                    "/channels",
                    params={"part": "snippet", "mine": "true"},
                    headers=_bearer(access_token),
                ),
            ),
            Channels,
        )
        channel = channels.items[0] if channels.items else None

        return PlatformProfile(
            external_id=user.sub,
            display_name=(channel.snippet.title if channel else None) or user.name,
        )

    async def search(
        self,
        access_token: str,  # noqa: ARG002
        query: str,
        *,
        limit: int,
    ) -> list[Track]:
        await self._quota.reserve(SEARCH_COST)
        found = _parse(
            await self._call(
                self._api.get(
                    "/search",
                    params={
                        "part": "id",
                        "type": "video",
                        "videoCategoryId": MUSIC_CATEGORY,
                        "maxResults": min(limit, SEARCH_LIMIT),
                        "q": query,
                        "key": self._api_key,
                    },
                ),
            ),
            SearchPage,
        )
        ids = [item.id.video_id for item in found.items if item.id.video_id]
        if not ids:
            return []

        await self._quota.reserve(READ_COST)
        videos = _parse(
            await self._call(
                self._api.get(
                    "/videos",
                    params={
                        "part": "snippet,contentDetails",
                        "id": ",".join(ids),
                        "key": self._api_key,
                    },
                ),
            ),
            Videos,
        )
        by_id = {video.id: video for video in videos.items}

        return [_to_track(by_id[video_id]) for video_id in ids if video_id in by_id]

    async def _videos(self, access_token: str, ids: list[str]) -> dict[str, Video]:
        found: dict[str, Video] = {}
        for start in range(0, len(ids), PAGE):
            await self._quota.reserve(READ_COST)
            page = _parse(
                await self._call(
                    self._api.get(
                        "/videos",
                        params={
                            "part": "snippet,contentDetails",
                            "id": ",".join(ids[start : start + PAGE]),
                            "maxResults": PAGE,
                        },
                        headers=_bearer(access_token),
                    ),
                ),
                Videos,
            )
            found |= {video.id: video for video in page.items}

        return found

    async def _likes_playlist(self, access_token: str) -> str | None:
        await self._quota.reserve(READ_COST)
        channels = _parse(
            await self._call(
                self._api.get(
                    "/channels",
                    params={"part": "contentDetails", "mine": "true"},
                    headers=_bearer(access_token),
                ),
            ),
            Channels,
        )

        return (
            channels.items[0].content_details.related_playlists.likes
            if channels.items
            else None
        )

    async def _items_page(
        self,
        access_token: str,
        playlist_id: str,
        page_token: str | None,
    ) -> PlaylistItems:
        await self._quota.reserve(READ_COST)
        params: dict[str, str | int] = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": PAGE,
        }
        if page_token:
            params["pageToken"] = page_token

        return _parse(
            await self._call(
                self._api.get(
                    "/playlistItems",
                    params=params,
                    headers=_bearer(access_token),
                ),
            ),
            PlaylistItems,
        )

    async def _items(self, access_token: str, playlist_id: str) -> list[PlaylistItem]:
        items: list[PlaylistItem] = []
        page_token: str | None = None
        while True:
            page = await self._items_page(access_token, playlist_id, page_token)
            items += page.items
            if not page.next_page_token:
                return items

            page_token = page.next_page_token

    async def saved_tracks(
        self,
        access_token: str,
        *,
        cursor: str | None,
    ) -> SavedTracksPage:
        likes, _, page_token = (cursor or "").partition(":")
        if likes:
            page = await self._items_page(access_token, likes, page_token or None)
        else:
            likes = LIKED_MUSIC
            try:
                page = await self._items_page(access_token, likes, None)
            except PlatformNotFoundError:
                found = await self._likes_playlist(access_token)
                if found is None:
                    return SavedTracksPage(total=0)

                likes = found
                page = await self._items_page(access_token, likes, None)

        videos = await self._videos(
            access_token,
            [item.content_details.video_id for item in page.items],
        )

        saved: list[SavedTrack] = []
        for item in page.items:
            video = videos.get(item.content_details.video_id)
            if video is None:
                saved.append(
                    SavedTrack(
                        track=Track(
                            platform=Platforms.YOUTUBE,
                            platform_id=item.content_details.video_id,
                            title="",
                        ),
                        ignored=True,
                    ),
                )
                continue

            saved.append(
                SavedTrack(
                    track=_to_track(video),
                    added_at=item.snippet.published_at,
                    ignored=likes != LIKED_MUSIC
                    and video.snippet.category_id != MUSIC_CATEGORY,
                ),
            )

        return SavedTracksPage(
            total=page.page_info.total_results,
            items=saved,
            next=f"{likes}:{page.next_page_token}" if page.next_page_token else None,
        )

    async def user_playlists(self, access_token: str) -> list[RemotePlaylist]:
        playlists: list[RemotePlaylist] = []
        page_token: str | None = None
        while True:
            await self._quota.reserve(READ_COST)
            params: dict[str, str | int] = {
                "part": "snippet",
                "mine": "true",
                "maxResults": PAGE,
            }
            if page_token:
                params["pageToken"] = page_token
            page = _parse(
                await self._call(
                    self._api.get(
                        "/playlists",
                        params=params,
                        headers=_bearer(access_token),
                    ),
                ),
                Playlists,
            )
            playlists += [_to_playlist(playlist) for playlist in page.items]
            if not page.next_page_token:
                return playlists

            page_token = page.next_page_token

    async def playlist_tracks(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> PlaylistTracks:
        ids = [
            item.content_details.video_id
            for item in await self._items(access_token, platform_playlist_id)
        ]
        videos = await self._videos(access_token, ids)
        found = [videos[video_id] for video_id in ids if video_id in videos]
        music = sum(video.snippet.category_id == MUSIC_CATEGORY for video in found)

        return PlaylistTracks(
            tracks=[_to_track(video) for video in found],
            music=bool(found) and music >= len(found) * MUSIC_SHARE,
        )

    async def playlist_track_ids(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> list[str]:
        return [
            item.content_details.video_id
            for item in await self._items(access_token, platform_playlist_id)
        ]

    async def _rate(self, access_token: str, video_id: str, rating: str) -> None:
        await self._quota.reserve(WRITE_COST)
        await self._call(
            self._api.post(
                "/videos/rate",
                params={"id": video_id, "rating": rating},
                headers=_bearer(access_token),
            ),
        )

    async def save_tracks(self, access_token: str, platform_ids: list[str]) -> None:
        for video_id in platform_ids:
            await self._rate(access_token, video_id, "like")

    async def unsave_tracks(self, access_token: str, platform_ids: list[str]) -> None:
        for video_id in platform_ids:
            await self._rate(access_token, video_id, "none")

    async def create_playlist(
        self,
        access_token: str,
        *,
        name: str,
        description: str | None,
    ) -> PlatformPlaylist:
        await self._quota.reserve(WRITE_COST)
        created = _parse(
            await self._call(
                self._api.post(
                    "/playlists",
                    params={"part": "snippet,status"},
                    json={
                        "snippet": {"title": name, "description": description or ""},
                        "status": {"privacyStatus": "private"},
                    },
                    headers=_bearer(access_token),
                ),
            ),
            Playlist,
        )

        return PlatformPlaylist(platform_id=created.id, snapshot_id=created.etag)

    async def update_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        *,
        name: str,
        description: str | None,
    ) -> None:
        await self._quota.reserve(WRITE_COST)
        await self._call(
            self._api.put(
                "/playlists",
                params={"part": "snippet"},
                json={
                    "id": platform_playlist_id,
                    "snippet": {"title": name, "description": description or ""},
                },
                headers=_bearer(access_token),
            ),
        )

    async def delete_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
    ) -> None:
        await self._quota.reserve(WRITE_COST)
        await self._call(
            self._api.delete(
                "/playlists",
                params={"id": platform_playlist_id},
                headers=_bearer(access_token),
            ),
        )

    async def add_to_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None:
        for video_id in platform_ids:
            await self._quota.reserve(WRITE_COST)
            await self._call(
                self._api.post(
                    "/playlistItems",
                    params={"part": "snippet"},
                    json={
                        "snippet": {
                            "playlistId": platform_playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id,
                            },
                        },
                    },
                    headers=_bearer(access_token),
                ),
            )

        return None

    async def remove_from_playlist(
        self,
        access_token: str,
        platform_playlist_id: str,
        platform_ids: list[str],
    ) -> str | None:
        wanted = set(platform_ids)
        for item in await self._items(access_token, platform_playlist_id):
            if item.content_details.video_id not in wanted:
                continue

            await self._quota.reserve(WRITE_COST)
            await self._call(
                self._api.delete(
                    "/playlistItems",
                    params={"id": item.id},
                    headers=_bearer(access_token),
                ),
            )

        return None

    async def devices(self, access_token: str) -> list[PlaybackDevice]:
        _unsupported(access_token)

    async def play(self, access_token: str, request: PlaybackRequest) -> None:
        _unsupported(access_token, request)

    async def close(self) -> None:
        for client in (self._accounts, self._token_client, self._userinfo, self._api):
            await client.aclose()


class YouTubeConnection(Singleton[YouTubeService | None]):
    @classmethod
    def create(cls) -> YouTubeService | None:
        youtube = settings.youtube
        if not (youtube.client_id and youtube.client_secret and youtube.api_key):
            return None

        def client(base_url: str) -> httpx.AsyncClient:
            return httpx.AsyncClient(base_url=base_url, timeout=youtube.timeout_seconds)

        redis = RedisConnection.get()

        return YouTubeService(
            client(youtube.accounts_url),
            client(youtube.oauth_url),
            client(youtube.userinfo_url),
            client(youtube.api_url),
            client_id=youtube.client_id,
            client_secret=youtube.client_secret.get_secret_value(),
            api_key=youtube.api_key.get_secret_value(),
            redirect_uri=youtube.redirect_uri,
            scopes=youtube.scopes,
            quota=Quota(
                redis,
                Platforms.YOUTUBE,
                daily=youtube.daily_quota,
                name="YouTube",
                per_account=youtube.daily_push_units,
                per_account_finds=youtube.daily_find_units,
            ),
            refresh_token_lifetime=timedelta(days=youtube.refresh_token_days)
            if youtube.refresh_token_days
            else None,
            pause=PlatformPause(redis, Platforms.YOUTUBE, name="YouTube"),
        )

    @classmethod
    async def dispose(cls, instance: YouTubeService | None) -> None:
        if instance is not None:
            await instance.close()
