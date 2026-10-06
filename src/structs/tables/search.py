from typing import Any

from sqlalchemy import Connection
from sqlalchemy import event
from sqlalchemy import text

from .base import Base


ALEF = chr(0x0627)
ALEFS = "".join(map(chr, (0x0623, 0x0625, 0x0622, 0x0671)))
FOLDED_FROM = (
    ALEFS
    + chr(0x0629)
    + chr(0x0649)
    + chr(0x0640)
    + "".join(map(chr, range(0x064B, 0x0653)))
)
FOLDED_TO = ALEF * len(ALEFS) + chr(0x0647) + chr(0x064A)

SEARCH_DDL = [
    "create extension if not exists pg_trgm",
    "create extension if not exists unaccent",
    "create extension if not exists btree_gist",
    (
        "create or replace function search_fold(value text) returns text "
        "language sql immutable strict parallel safe "
        "return translate("
        "lower(public.unaccent('public.unaccent'::regdictionary, value)), "
        f"'{FOLDED_FROM}', '{FOLDED_TO}')"
    ),
    (
        "create or replace function track_search_text(title text, artists text[], "
        "album text) returns text language sql immutable parallel safe "
        "return search_fold(coalesce(title, '') || ' ' "
        "|| coalesce(array_to_string(artists, ' '), '') || ' ' || coalesce(album, ''))"
    ),
]


@event.listens_for(Base.metadata, "before_create")
def _search_functions(_target: object, connection: Connection, **_: Any) -> None:
    for statement in SEARCH_DDL:
        connection.execute(text(statement))
