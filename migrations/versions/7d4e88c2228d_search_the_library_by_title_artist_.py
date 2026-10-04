"""search the library by title, artist, album, and playlist name

Revision ID: 7d4e88c2228d
Revises: 4ce299a1c548
Create Date: 2026-10-04 04:59:04.270948

"""

from typing import Sequence
from typing import Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7d4e88c2228d"
down_revision: Union[str, Sequence[str], None] = "4ce299a1c548"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ALEFS = "".join(map(chr, (0x0623, 0x0625, 0x0622, 0x0671)))
FOLDED_FROM = (
    ALEFS
    + chr(0x0629)
    + chr(0x0649)
    + chr(0x0640)
    + "".join(map(chr, range(0x064B, 0x0653)))
)
FOLDED_TO = chr(0x0627) * len(ALEFS) + chr(0x0647) + chr(0x064A)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("create extension if not exists pg_trgm")
    op.execute("create extension if not exists unaccent")
    op.execute(
        "create or replace function search_fold(value text) returns text "
        "language sql immutable strict parallel safe "
        "return translate("
        "lower(public.unaccent('public.unaccent'::regdictionary, value)), "
        f"'{FOLDED_FROM}', '{FOLDED_TO}')"
    )
    op.execute(
        "create or replace function track_search_text(title text, artists text[], "
        "album text) returns text language sql immutable parallel safe "
        "return search_fold(coalesce(title, '') || ' ' "
        "|| coalesce(array_to_string(artists, ' '), '') || ' ' || coalesce(album, ''))"
    )
    op.execute(
        "create index ix_tracks_search on tracks "
        "using gin (track_search_text(title, artists, album) gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop index if exists ix_tracks_search")
    op.execute("drop function if exists track_search_text(text, text[], text)")
    op.execute("drop function if exists search_fold(text)")
