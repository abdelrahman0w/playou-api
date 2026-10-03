import argparse
from datetime import UTC
from datetime import datetime

from src.actions import auth as auth_actions
from src.jobs import Job
from src.providers import DatabaseSessions


async def prune_auth(
    _: argparse.Namespace,
) -> object:
    return await auth_actions.prune_auth(
        DatabaseSessions.get(),
        now=datetime.now(UTC),
    )


JOBS: dict[str, Job] = {
    "prune_auth": Job(
        run=prune_auth,
        help="drop the expired sessions, and the codes used or expired",
        monitor_every_seconds=24 * 60 * 60,
        cron="30 0 * * *",
    ),
}
