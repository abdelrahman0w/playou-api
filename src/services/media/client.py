import hashlib
import hmac
from datetime import UTC
from datetime import datetime
from urllib.parse import quote
from urllib.parse import urlsplit

import httpx

from src.exceptions import MediaUnavailableError
from src.settings import settings
from src.utils import Singleton


IMMUTABLE = "public, max-age=31536000, immutable"


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def sign(
    method: str,
    url: str,
    body: bytes,
    *,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    now: datetime,
) -> dict[str, str]:
    parts = urlsplit(url)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    payload = hashlib.sha256(body).hexdigest()
    headers = {
        "host": parts.netloc,
        "x-amz-content-sha256": payload,
        "x-amz-date": stamp,
    }
    signed = ";".join(headers)
    canonical = "\n".join(
        [
            method,
            quote(parts.path, safe="/-_.~"),
            parts.query,
            "".join(f"{name}:{value}\n" for name, value in headers.items()),
            signed,
            payload,
        ],
    )
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            stamp,
            scope,
            hashlib.sha256(canonical.encode()).hexdigest(),
        ],
    )
    key = f"AWS4{secret_access_key}".encode()
    for part in (day, region, "s3", "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()

    return headers | {
        "authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}"
        ),
    }


class MediaService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        public_url: str,
    ) -> None:
        self._client = client
        self._base = f"{endpoint.rstrip('/')}/{bucket}"
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region = region
        self._public_url = public_url.rstrip("/")

    def url(self, key: str) -> str:
        return f"{self._public_url}/{key}"

    async def _send(
        self,
        method: str,
        key: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        url = f"{self._base}/{key}"
        signed = sign(
            method,
            url,
            body,
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            region=self._region,
            now=datetime.now(UTC),
        )
        try:
            response = await self._client.request(
                method,
                url,
                content=body,
                headers=signed | (headers or {}),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MediaUnavailableError(
                f"The picture could not be stored, the bucket answered "
                f"{exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise MediaUnavailableError("The picture could not be stored") from exc

    async def put(self, key: str, body: bytes, *, content_type: str) -> None:
        await self._send(
            "PUT",
            key,
            body,
            {"content-type": content_type, "cache-control": IMMUTABLE},
        )

    async def delete(self, key: str) -> None:
        await self._send("DELETE", key)

    async def close(self) -> None:
        await self._client.aclose()


class AvatarsConnection(Singleton[MediaService | None]):
    @classmethod
    def create(cls) -> MediaService | None:
        media, avatars = settings.media, settings.avatars
        if not (
            settings.avatars_enabled
            and media.endpoint
            and media.access_key_id
            and media.secret_access_key
            and avatars.bucket
            and avatars.public_url
        ):
            return None

        return MediaService(
            httpx.AsyncClient(timeout=media.timeout_seconds),
            endpoint=media.endpoint,
            bucket=avatars.bucket,
            access_key_id=media.access_key_id,
            secret_access_key=media.secret_access_key.get_secret_value(),
            region=media.region,
            public_url=avatars.public_url,
        )

    @classmethod
    async def dispose(cls, instance: MediaService | None) -> None:
        if instance is not None:
            await instance.close()
