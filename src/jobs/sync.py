import argparse
from datetime import UTC
from datetime import datetime

from src.actions import sync as sync_actions
from src.jobs import Job
from src.providers import DatabaseSessions
from src.providers import RedisConnection
from src.services import available_platforms


async def push_library_changes(
    _: argparse.Namespace,
) -> object:
    return await sync_actions.push_pending(
        DatabaseSessions.get(),
        available_platforms(),
        now=datetime.now(UTC),
    )


async def prune_sync_operations(
    _: argparse.Namespace,
) -> object:
    return await sync_actions.prune_finished(
        DatabaseSessions.get(),
        now=datetime.now(UTC),
    )


async def import_libraries(
    _: argparse.Namespace,
) -> object:
    return await sync_actions.run_imports(
        DatabaseSessions.get(),
        available_platforms(),
        now=datetime.now(UTC),
    )


async def copy_libraries(
    _: argparse.Namespace,
) -> object:
    return await sync_actions.run_copies(
        DatabaseSessions.get(),
        RedisConnection.get(),
        available_platforms(),
        now=datetime.now(UTC),
    )


JOBS: dict[str, Job] = {
    "push_library_changes": Job(
        run=push_library_changes,
        help="push the library's changes the platforms do not have yet",
    ),
    "import_libraries": Job(
        run=import_libraries,
        help="import the linked accounts' libraries that are due, and the asked for",
    ),
    "copy_libraries": Job(
        run=copy_libraries,
        help="find the songs being copied to another app, then send them there",
    ),
    "prune_sync_operations": Job(
        run=prune_sync_operations,
        help="drop the sync operations finished longer ago than SYNC_RETENTION_DAYS",
        monitor_every_seconds=24 * 60 * 60,
        cron="0 1 * * *",
    ),
}
