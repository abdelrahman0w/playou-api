import httpx
from pydantic import TypeAdapter
from pydantic import ValidationError

from src.exceptions import PlatformUnavailableError
from src.services.lrclib.models import LrclibRecord
from src.settings import settings
from src.utils import Singleton


RECORDS = TypeAdapter(list[LrclibRecord])


class LrclibService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _get(self, path: str, params: dict[str, str | int]) -> httpx.Response:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise PlatformUnavailableError("LRCLIB could not be reached") from exc
        if response.status_code != httpx.codes.NOT_FOUND and response.is_error:
            raise PlatformUnavailableError(
                f"LRCLIB responded with status {response.status_code}",
            )

        return response

    async def get(
        self,
        *,
        title: str,
        artist: str,
        album: str,
        duration_seconds: int,
    ) -> LrclibRecord | None:
        response = await self._get(
            "/get",
            {
                "track_name": title,
                "artist_name": artist,
                "album_name": album,
                "duration": duration_seconds,
            },
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return None

        try:
            return LrclibRecord.model_validate_json(response.content)
        except ValidationError as exc:
            raise PlatformUnavailableError("LRCLIB answered something else") from exc

    async def search(self, *, title: str, artist: str) -> list[LrclibRecord]:
        response = await self._get(
            "/search",
            {"track_name": title, "artist_name": artist},
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return []

        try:
            return RECORDS.validate_json(response.content)
        except ValidationError as exc:
            raise PlatformUnavailableError("LRCLIB answered something else") from exc

    async def close(self) -> None:
        await self._client.aclose()


class LrclibConnection(Singleton[LrclibService | None]):
    @classmethod
    def create(cls) -> LrclibService | None:
        lyrics = settings.lyrics
        if not lyrics.enabled:
            return None

        return LrclibService(
            httpx.AsyncClient(
                base_url=lyrics.lrclib_url,
                headers={"User-Agent": f"PlaYou ({settings.app.web_url})"},
                timeout=lyrics.timeout_seconds,
            ),
        )

    @classmethod
    async def dispose(cls, instance: LrclibService | None) -> None:
        if instance is not None:
            await instance.close()
