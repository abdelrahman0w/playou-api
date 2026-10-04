import argparse
import asyncio
import time
from contextlib import nullcontext
from datetime import datetime

import uvloop

from src.jobs import Job
from src.jobs import accounts
from src.jobs import auth
from src.jobs import data
from src.jobs import sync
from src.providers import DatabaseConnection
from src.providers import DatabaseSessions
from src.providers import RedisConnection
from src.providers import enable_async_error_tracking
from src.providers import logger
from src.providers import monitor_job
from src.providers import setup_error_tracking
from src.providers import setup_logging
from src.services import ResendConnection
from src.services import SpotifyConnection
from src.services import YouTubeConnection
from src.settings import settings
from src.utils import connect_singletons
from src.utils import cron_matches


SINGLETONS = (
    DatabaseConnection,
    DatabaseSessions,
    RedisConnection,
    ResendConnection,
    SpotifyConnection,
    YouTubeConnection,
)

JOBS: dict[str, Job] = {
    **accounts.JOBS,
    **auth.JOBS,
    **data.JOBS,
    **sync.JOBS,
}


SCHEDULE = "schedule"


def _elapsed_ms(
    started: float,
) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="jobs")
    subcommands = parser.add_subparsers(
        dest="job",
        required=True,
        metavar="job",
    )

    subcommands.add_parser(
        SCHEDULE,
        help="run every job on its cron, until stopped, for local development",
    )
    for name, job in sorted(JOBS.items()):
        job.arguments(
            subcommands.add_parser(
                name,
                help=job.help,
                description=job.help,
            ),
        )

    return parser.parse_args(argv)


async def run_job(
    name: str,
    args: argparse.Namespace,
) -> None:
    job = JOBS[name]
    monitor = (
        monitor_job(name, job.monitor_every_seconds)
        if job.monitor_every_seconds
        else nullcontext()
    )
    started = time.perf_counter()

    with logger.contextualize(job=name), monitor:
        logger.info(
            "[Jobs] Job Started",
            job_name=name,
        )

        try:
            await job.run(args)
        except Exception:
            logger.exception(
                "[Jobs] Job Failed",
                job_name=name,
                duration_ms=_elapsed_ms(started),
            )

            raise

        logger.info(
            "[Jobs] Job Finished",
            job_name=name,
            duration_ms=_elapsed_ms(started),
        )


async def _run_quietly(
    name: str,
) -> None:
    try:
        await run_job(name, parse_args([name]))
    except Exception:  # noqa: S110
        pass


async def schedule() -> None:
    logger.info(
        "[Jobs] Scheduling",
        jobs=sorted(name for name, job in JOBS.items() if job.cron),
    )
    running: dict[str, asyncio.Task[None]] = {}

    while True:
        now = datetime.now().astimezone()
        for name, job in sorted(JOBS.items()):
            busy = name in running and not running[name].done()
            if job.cron and cron_matches(job.cron, now) and not busy:
                running[name] = asyncio.create_task(_run_quietly(name))

        later = datetime.now().astimezone()
        await asyncio.sleep(60 - later.second - later.microsecond / 1_000_000)


async def run(
    args: argparse.Namespace,
) -> None:
    enable_async_error_tracking()

    async with connect_singletons(*SINGLETONS):
        if args.job == SCHEDULE:
            await schedule()
        else:
            await run_job(args.job, args)


def main(
    argv: list[str] | None = None,
) -> None:
    setup_logging(
        level=settings.app.log_level,
        json_logs=settings.app.log_json,
    )
    setup_error_tracking(
        settings.error_tracking,
        settings.app,
    )

    uvloop.run(run(parse_args(argv)))


if __name__ == "__main__":
    main()
