from collections.abc import Awaitable
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel
from pydantic import SecretStr
from pydantic import ValidationError

from src.exceptions import InvalidOAuthStateError
from src.exceptions import PlatformError
from src.exceptions import PlatformReconnectRequiredError
from src.exceptions import PlatformTimeoutError
from src.exceptions import PlatformUnavailableError
from src.services.spotify.models import SpotifyError
from src.services.spotify.models import SpotifySearch
from src.services.spotify.models import SpotifyToken
from src.services.spotify.models import SpotifyTokenError
from src.services.spotify.models import SpotifyTrack
from src.services.spotify.models import SpotifyUser
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.models import Capabilities
from src.structs.models import PlatformProfile
from src.structs.models import PlatformTokens
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


async def _send(
    request: Awaitable[httpx.Response],
) -> httpx.Response:
    try:
        return await request
    except httpx.TimeoutException as exc:
        raise PlatformTimeoutError("Spotify took too long to respond") from exc
    except httpx.RequestError as exc:
        raise PlatformUnavailableError("Spotify could not be reached") from exc


def _check(
    response: httpx.Response,
) -> httpx.Response:
    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise PlatformReconnectRequiredError("Spotify no longer accepts the account")
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise PlatformUnavailableError("Spotify is limiting the requests, try later")
    if response.is_error:
        raise PlatformError(
            f"Spotify responded with status {response.status_code}"
            + (f", {reason}" if (reason := _reason(response)) else ""),
        )

    return response


def _reason(
    response: httpx.Response,
) -> str | None:
    try:
        return SpotifyError.model_validate_json(response.content).error.message
    except ValidationError:
        return None


async def _call(
    request: Awaitable[httpx.Response],
) -> httpx.Response:
    return _check(await _send(request))


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
        title=track.name,
        artists=[artist.name for artist in track.artists],
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
    ) -> None:
        self._accounts = accounts
        self._api = api
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._search_max_limit = search_max_limit
        self.refresh_token_lifetime = refresh_token_lifetime

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
                "scope": " ".join(self._scopes),
            },
        )

        return f"{self._accounts.base_url.join('/authorize')}?{query}"

    async def _token(self, form: dict[str, str]) -> SpotifyToken | SpotifyTokenError:
        response = await _send(
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
        response = await _call(
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
        response = await _call(
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
        )

    @classmethod
    async def dispose(cls, instance: SpotifyService | None) -> None:
        if instance is not None:
            await instance.close()
