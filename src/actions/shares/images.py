import asyncio
import base64
import hashlib
import io
from urllib.parse import urlsplit

import httpx
from PIL import Image
from PIL import UnidentifiedImageError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.providers import logger
from src.settings import settings
from src.structs.enums import CacheKeys
from src.utils.share_image import draw_share_image
from src.utils.single_flight import single_flight


DESIGN = 3
COVER_HOSTS = frozenset(
    {
        "i.scdn.co",
        "i.ytimg.com",
        "mosaic.scdn.co",
        "image-cdn-ak.spotifycdn.com",
        "image-cdn-fa.spotifycdn.com",
    },
)
COVER_BYTES = 5 * 1024 * 1024
COVER_PIXELS = 25_000_000
COVER_SECONDS = 5.0

_DRAWING = asyncio.Semaphore(2)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=COVER_SECONDS)


def _decode(data: bytes) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > COVER_PIXELS:
                return None

            return image.convert("RGB")
    except UnidentifiedImageError, OSError, Image.DecompressionBombError:
        return None


async def _cover(url: str | None) -> Image.Image | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in COVER_HOSTS:
        return None

    data = bytearray()
    try:
        async with _client() as client, client.stream("GET", url) as response:
            if response.status_code != httpx.codes.OK:
                return None
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > COVER_BYTES:
                    return None
    except httpx.HTTPError:
        logger.warning("[Shares] Cover Unavailable", url=url)

        return None

    return await asyncio.to_thread(_decode, bytes(data))


async def _draw(
    redis: Redis,
    key: str,
    title: str,
    subtitle: str,
    cover_url: str | None,
) -> bytes:
    cover = await _cover(cover_url)
    async with _DRAWING:
        image = await asyncio.to_thread(draw_share_image, title, subtitle, cover)
    try:
        await redis.set(
            key,
            base64.b64encode(image).decode(),
            ex=settings.shares.image_cache_days * 24 * 60 * 60,
        )
    except RedisError:
        logger.warning("[Cache] Skipped - Redis Is Unavailable", key=key)

    return image


async def share_image(
    redis: Redis,
    *,
    title: str,
    subtitle: str,
    cover_url: str | None,
) -> bytes:
    digest = hashlib.sha256(
        "\n".join([str(DESIGN), title, subtitle, cover_url or ""]).encode(),
    ).hexdigest()
    key = CacheKeys.SHARE_IMAGE.format(digest=digest)

    try:
        cached = await redis.get(key)
    except RedisError:
        cached = None
    if cached:
        return base64.b64decode(cached)

    return await single_flight(
        key,
        lambda: _draw(redis, key, title, subtitle, cover_url),
    )
