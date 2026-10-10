import re

from src.structs.models.responses import LyricsLine


STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


def _ms(minutes: str, seconds: str) -> int:
    return round((int(minutes) * 60 + float(seconds.replace(":", "."))) * 1000)


def timed_lines(synced: str) -> list[LyricsLine]:
    lines: list[LyricsLine] = []
    for raw in synced.splitlines():
        stamps: list[int] = []
        rest = raw.strip()

        while match := STAMP.match(rest):
            stamps.append(_ms(match[1], match[2]))
            rest = rest[match.end() :]

        text = rest.strip()
        lines.extend(LyricsLine(at_ms=stamp, text=text) for stamp in stamps)

    return sorted(lines, key=lambda line: line.at_ms)
