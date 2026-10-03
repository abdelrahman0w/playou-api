import argparse
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass


def _no_arguments(
    _: argparse.ArgumentParser,
) -> None:
    return None


@dataclass(frozen=True)
class Job:
    run: Callable[[argparse.Namespace], Awaitable[object]]
    help: str
    arguments: Callable[[argparse.ArgumentParser], None] = _no_arguments
    monitor_every_seconds: int | None = None
    cron: str | None = None
