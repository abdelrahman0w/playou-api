import argparse
import asyncio
import signal
import time
from contextlib import nullcontext
from datetime import datetime

import uvloop

from src.jobs import Job
from src.jobs import accounts
from src.jobs import auth
from src.jobs import data
from src.jobs import sync
from src.jobs.worker import SyncWorker
from src.providers import DatabaseConnection
from src.providers import DatabaseSessions
from src.providers import RedisConnection
from src.providers import enable_async_error_tracking
from src.providers import logger
from src.providers import make_redis
from src.providers import monitor_job
from src.providers import setup_error_tracking
from src.providers import setup_logging
from src.services import ResendConnection
from src.services import SpotifyConnection
from src.services import YouTubeConnection
from src.services import available_platforms
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
WORKER = "worker"


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
        help="run every job on its cron and the sync worker, until stopped, locally",
    )
    subcommands.add_parser(
        WORKER,
        help="push, copy and import as they are asked for, and sweep what is due",
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


async def work(stop: asyncio.Event) -> None:
    waiting = make_redis(socket_timeout=settings.worker.wait_seconds + 5)
    try:
        await SyncWorker(
            DatabaseSessions.get(),
            RedisConnection.get(),
            waiting,
            available_platforms(),
        ).run(stop)
    finally:
        await waiting.aclose()


def _stopping() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    return stop


async def schedule() -> None:
    worker = asyncio.create_task(work(asyncio.Event()))
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
        if worker.done():
            worker.result()


async def run(
    args: argparse.Namespace,
) -> None:
    enable_async_error_tracking()

    async with connect_singletons(*SINGLETONS):
        if args.job == SCHEDULE:
            await schedule()
        elif args.job == WORKER:
            await work(_stopping())
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
