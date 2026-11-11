import io

from PIL import Image
from PIL import ImageOps
from PIL import UnidentifiedImageError

from src.settings import settings


AVATAR_SOURCE_PIXELS = 60_000_000
WEBP_QUALITY = 85
AVATAR_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")


def avatar_webp(data: bytes, *, size: int) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data), formats=AVATAR_FORMATS) as image:
            if image.width * image.height > AVATAR_SOURCE_PIXELS:
                return None

            upright = ImageOps.exif_transpose(image)
            clear = "A" in upright.getbands() or "transparency" in upright.info
            square = ImageOps.fit(
                upright.convert("RGBA" if clear else "RGB"),
                (size, size),
                method=Image.Resampling.LANCZOS,
            )
    except UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError:
        return None

    square.info = {}
    out = io.BytesIO()
    square.save(out, "WEBP", quality=WEBP_QUALITY, method=6)

    return out.getvalue()


def avatar_url(key: str | None) -> str | None:
    public = settings.avatars.public_url

    return f"{public.rstrip('/')}/{key}" if key and public else None
