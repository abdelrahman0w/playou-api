from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy import Text
from sqlalchemy import all_
from sqlalchemy import any_
from sqlalchemy import bindparam
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import QueryableAttribute


ROWS_PER_INSERT = 1000


def _array[T](column: QueryableAttribute[T], values: Iterable[T]) -> ColumnElement[Any]:
    return bindparam(None, list(values), type_=ARRAY(column.type))


def any_of[T](
    column: QueryableAttribute[T], values: Iterable[T]
) -> ColumnElement[bool]:
    return column == any_(_array(column, values))


def none_of[T](
    column: QueryableAttribute[T], values: Iterable[T]
) -> ColumnElement[bool]:
    return column != all_(_array(column, values))


def seen_on(
    column: QueryableAttribute[list[str]], platform: str
) -> ColumnElement[bool]:
    return literal(platform, Text) == any_(column)


def also_seen_on(
    column: QueryableAttribute[list[str]],
    platform: str,
) -> ColumnElement[list[str]]:
    return func.array_append(func.array_remove(column, platform), platform)


def not_seen_on(
    column: QueryableAttribute[list[str]],
    platform: str,
) -> ColumnElement[list[str]]:
    return func.array_remove(column, platform)


def only_seen_on(platform: str | None) -> ColumnElement[Any]:
    platforms: list[Any] = [platform] if platform else []

    return bindparam(None, platforms, type_=ARRAY(Text))
