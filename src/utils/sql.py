from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy import all_
from sqlalchemy import any_
from sqlalchemy import bindparam
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
