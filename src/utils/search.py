from sqlalchemy import ColumnElement
from sqlalchemy import func


MAX_WORDS = 8


def _escaped(word: str) -> str:
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def matching(expression: ColumnElement[str], query: str) -> list[ColumnElement[bool]]:
    return [
        expression.like(
            func.concat("%", func.search_fold(_escaped(word)), "%"),
            escape="\\",
        )
        for word in query.split()[:MAX_WORDS]
    ]
