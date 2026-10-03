import argparse
from datetime import UTC
from datetime import datetime

from src.actions import accounts as accounts_actions
from src.jobs import Job
from src.providers import DatabaseSessions
from src.services import ResendConnection
from src.services import available_platforms


async def check_expiring_accounts(
    _: argparse.Namespace,
) -> object:
    return await accounts_actions.check_expiring_accounts(
        DatabaseSessions.get(),
        available_platforms(),
        ResendConnection.get(),
        now=datetime.now(UTC),
    )


JOBS: dict[str, Job] = {
    "check_expiring_accounts": Job(
        run=check_expiring_accounts,
        help="warn the expiring accounts, and refresh the ones a refresh extends",
        monitor_every_seconds=24 * 60 * 60,
    ),
}
