import argparse

from src.actions import catalog as catalog_actions
from src.actions import library as library_actions
from src.jobs import Job
from src.providers import DatabaseSessions
from src.providers import RedisConnection
from src.providers import logger
from src.repositories import auth as auth_repositories


def _arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("email", help="the user's email")
    parser.add_argument(
        "--account",
        action="store_true",
        help="delete the account too, not only its library and its linked apps",
    )


def _merge_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only log the duplicates, without merging them",
    )


async def merge_tracks(args: argparse.Namespace) -> object:
    return await catalog_actions.merge_duplicates(
        DatabaseSessions.get(),
        dry_run=args.dry_run,
    )


async def delete_user_data(args: argparse.Namespace) -> object:
    session_factory = DatabaseSessions.get()
    async with session_factory() as session, session.begin():
        user_id = await auth_repositories.get_user_by_email(session, args.email)
        if user_id is None:
            logger.warning("[Data] No User With That Email")
            return {"deleted": False}

        if args.account:
            await library_actions.delete_user(session, RedisConnection.get(), user_id)
        else:
            await library_actions.clear_library(session, user_id, unlink=True)

    return {"deleted": True, "account": args.account}


JOBS: dict[str, Job] = {
    "delete_user_data": Job(
        run=delete_user_data,
        help="delete a user's library and linked apps, or with --account everything, "
        "regardless of DATA_DELETION_ENABLED",
        arguments=_arguments,
    ),
    "merge_tracks": Job(
        run=merge_tracks,
        help="merge the tracks saved twice for one song, and uppercase the isrcs",
        arguments=_merge_arguments,
    ),
}
