import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any


_in_flight: dict[str, asyncio.Future[Any]] = {}


async def single_flight[T](key: str, produce: Callable[[], Awaitable[T]]) -> T:
    if (pending := _in_flight.get(key)) is not None:
        return await asyncio.shield(pending)

    task = asyncio.ensure_future(produce())
    _in_flight[key] = task

    try:
        return await asyncio.shield(task)
    finally:
        if _in_flight.get(key) is task:
            del _in_flight[key]
