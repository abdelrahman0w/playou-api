import io
import re
from functools import cache
from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter
from PIL import ImageFont
from PIL import features


ASSETS = Path(__file__).resolve().parent.parent / "assets"
WIDTH, HEIGHT = 1200, 630
COVER, MARGIN, RADIUS = 470, 80, 28
TEXT_LEFT = MARGIN + COVER + 64
TEXT_WIDTH = WIDTH - TEXT_LEFT - MARGIN
FALLBACK_TONE = (109, 40, 217)
DARK = (9, 9, 11)
ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
SHAPES = features.check("raqm")


@cache
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(ASSETS / "fonts" / name, size)


@cache
def _logo(size: int) -> Image.Image:
    with Image.open(ASSETS / "logo.png") as logo:
        return logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def _font_for(text: str, weight: str, size: int) -> ImageFont.FreeTypeFont:
    family = "NotoSansArabic" if ARABIC.search(text) else "Inter"

    return _font(f"{family}-{weight}.ttf", size)


def _right_to_left(text: str) -> bool:
    for char in text:
        if ARABIC.match(char):
            return True
        if char.isalpha():
            return False

    return False


def _direction(text: str) -> str | None:
    if not SHAPES:
        return None

    return "rtl" if _right_to_left(text) else "ltr"


def _width(font: ImageFont.FreeTypeFont, text: str) -> float:
    return font.getlength(text, direction=_direction(text))


def _cut(font: ImageFont.FreeTypeFont, text: str, *, always: bool = False) -> str:
    if not always and _width(font, text) <= TEXT_WIDTH:
        return text
    while len(text) > 1 and _width(font, f"{text}…") > TEXT_WIDTH:
        text = text[:-1].rstrip()

    return f"{text}…"


def _lines(font: ImageFont.FreeTypeFont, text: str, most: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        joined = f"{line} {word}" if line else word
        if not line or _width(font, joined) <= TEXT_WIDTH:
            line = joined
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    kept = [_cut(font, line) for line in lines[:most]]
    if len(lines) > most:
        kept[-1] = _cut(font, kept[-1].removesuffix("…"), always=True)

    return kept


def _tone(cover: Image.Image | None) -> tuple[int, int, int]:
    if cover is None:
        return FALLBACK_TONE

    r, g, b = cover.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))  # type: ignore[misc]

    return (round(r * 0.8), round(g * 0.8), round(b * 0.8))


def _background(tone: tuple[int, int, int]) -> Image.Image:
    fade = Image.linear_gradient("L").resize((WIDTH, HEIGHT))

    return Image.composite(
        Image.new("RGB", (WIDTH, HEIGHT), DARK),
        Image.new("RGB", (WIDTH, HEIGHT), tone),
        fade,
    )


def _rounded(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), RADIUS, fill=255)

    return mask


def _cover(card: Image.Image, cover: Image.Image | None) -> None:
    top = (HEIGHT - COVER) // 2
    shadow = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (MARGIN, top + 24, MARGIN + COVER, top + 24 + COVER),
        RADIUS,
        fill=115,
    )
    card.paste(DARK, (0, 0), shadow.filter(ImageFilter.GaussianBlur(36)))

    if cover is None:
        art = Image.new("RGB", (COVER, COVER), (24, 24, 27))
        logo = _logo(180)
        art.paste(logo, ((COVER - 180) // 2, (COVER - 180) // 2), logo)
    else:
        art = cover.resize((COVER, COVER), Image.Resampling.LANCZOS)
    card.paste(art, (MARGIN, top), _rounded(COVER))


def _write(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    top: float,
    fill: tuple[int, ...],
) -> None:
    direction = _direction(text)
    if direction == "rtl":
        draw.text(
            (WIDTH - MARGIN, top),
            text,
            font=font,
            fill=fill,
            anchor="ra",
            direction=direction,
        )
    else:
        draw.text((TEXT_LEFT, top), text, font=font, fill=fill, direction=direction)


def draw_share_image(
    title: str,
    artists: str,
    cover: Image.Image | None,
) -> bytes:
    card = _background(_tone(cover))
    _cover(card, cover)
    draw = ImageDraw.Draw(card, "RGBA")

    title_font = _font_for(title, "Bold", 60)
    titled = _lines(title_font, title, 2)
    title_step = 88 if ARABIC.search(title) else 76
    artists_font = _font_for(artists, "Medium", 36)
    credited = _cut(artists_font, " ".join(artists.split())) if artists else ""
    gap = 24 if ARABIC.search(title) else 10
    height = len(titled) * title_step + (gap + 48 if credited else 0)
    top = (HEIGHT - height) / 2 - 40

    for line in titled:
        _write(draw, line, title_font, top, (250, 250, 250))
        top += title_step
    if credited:
        _write(draw, credited, artists_font, top + gap, (250, 250, 250, 180))

    logo = _logo(56)
    brand = _font("Inter-Bold.ttf", 40)
    bottom = HEIGHT - MARGIN - 56
    card.paste(logo, (TEXT_LEFT, bottom), logo)
    draw.text(
        (TEXT_LEFT + 56 + 18, bottom + 28),
        "PlaYou",
        font=brand,
        fill=(250, 250, 250),
        anchor="lm",
    )

    output = io.BytesIO()
    card.save(output, "JPEG", quality=88)

    return output.getvalue()
