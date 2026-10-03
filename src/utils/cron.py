from datetime import datetime


def _values(
    spec: str,
    low: int,
    high: int,
) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        base, _, step = part.partition("/")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            first, last = base.split("-")
            start, end = int(first), int(last)
        else:
            start = int(base)
            end = high if step else start

        values.update(range(start, end + 1, int(step) if step else 1))

    return values


def cron_matches(
    expression: str,
    at: datetime,
) -> bool:
    minute, hour, day, month, weekday = expression.split()

    return (
        at.minute in _values(minute, 0, 59)
        and at.hour in _values(hour, 0, 23)
        and at.day in _values(day, 1, 31)
        and at.month in _values(month, 1, 12)
        and at.isoweekday() % 7 in _values(weekday, 0, 6)
    )
