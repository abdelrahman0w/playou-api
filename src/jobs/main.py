import argparse
import time
from contextlib import nullcontext

import uvloop

from src.jobs import Job
from src.jobs import accounts
from src.jobs import auth
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
from src.settings import settings
from src.utils import connect_singletons


SINGLETONS = (
    DatabaseConnection,
    DatabaseSessions,
    RedisConnection,
    ResendConnection,
    SpotifyConnection,
)

JOBS: dict[str, Job] = {
    **accounts.JOBS,
    **auth.JOBS,
    **sync.JOBS,
}


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


async def run(
    args: argparse.Namespace,
) -> None:
    enable_async_error_tracking()

    async with connect_singletons(*SINGLETONS):
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
