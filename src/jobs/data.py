import argparse
import sys
from base64 import urlsafe_b64encode
from datetime import UTC
from datetime import datetime
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02

from src.actions import auth as auth_actions
from src.actions import catalog as catalog_actions
from src.actions import library as library_actions
from src.jobs import Job
from src.providers import DatabaseSessions
from src.providers import RedisConnection
from src.providers import logger
from src.repositories import auth as auth_repositories
from src.repositories import messages as messages_repositories
from src.repositories import people as people_repositories
from src.services import AvatarsConnection
from src.services import available_platforms


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


def _reports_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="how many of the most reported lyrics to list",
    )


def _hide_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("track_id", type=UUID, help="the song whose lyrics to hide")


async def push_keys(_: argparse.Namespace) -> object:
    vapid = Vapid02()
    vapid.generate_keys()
    public = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    private = vapid.private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    sys.stdout.write(
        f"MESSAGES_PUSH_PUBLIC_KEY={urlsafe_b64encode(public).rstrip(b'=').decode()}\n"
        f"MESSAGES_PUSH_PRIVATE_KEY={urlsafe_b64encode(private).rstrip(b'=').decode()}\n",
    )

    return {"written": "to the terminal, not the logs"}


async def user_reports(args: argparse.Namespace) -> object:
    async with DatabaseSessions.get()() as session:
        return await people_repositories.user_reports(session, limit=args.limit)


async def message_reports(args: argparse.Namespace) -> object:
    async with DatabaseSessions.get()() as session:
        return await messages_repositories.message_reports(session, limit=args.limit)


async def lyrics_reports(args: argparse.Namespace) -> object:
    return await catalog_actions.lyrics_reports(
        DatabaseSessions.get(),
        limit=args.limit,
    )


async def hide_lyrics(args: argparse.Namespace) -> object:
    hidden = await catalog_actions.hide_lyrics(
        DatabaseSessions.get(),
        args.track_id,
        now=datetime.now(UTC),
    )

    return {"hidden": hidden}


def _restore_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("email", help="the user's email")
    parser.add_argument(
        "since",
        nargs="?",
        type=datetime.fromisoformat,
        help="the earliest removal to undo, 2026-11-09T13:31:00+00:00",
    )
    parser.add_argument(
        "until",
        nargs="?",
        type=datetime.fromisoformat,
        help="the removals before this are undone, 2026-11-09T13:32:00+00:00",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="undo every removal an app's import made, whenever it was, "
        "the songs removed in playou stay removed",
    )


async def restore_playlist_songs(args: argparse.Namespace) -> object:
    if args.all == (args.since is not None or args.until is not None) or (
        not args.all and (args.since is None or args.until is None)
    ):
        message = "give either since and until, or --all"
        raise SystemExit(message)

    async with DatabaseSessions.get()() as session, session.begin():
        user_id = await auth_repositories.get_user_by_email(session, args.email)
        if user_id is None:
            logger.warning("[Data] No User With That Email")
            return {"restored": []}

        playlist_ids = await library_actions.restore_removed(
            session,
            available_platforms(),
            user_id,
            since=args.since,
            until=args.until,
            now=datetime.now(UTC),
        )

    return {"restored": [str(playlist_id) for playlist_id in playlist_ids]}


def _avatar_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("username", help="whose profile picture to take down")


async def remove_avatar(args: argparse.Namespace) -> object:
    async with DatabaseSessions.get()() as session, session.begin():
        user = await people_repositories.by_username(session, args.username)
        if user is None:
            logger.warning("[Data] No User With That Username")
            return {"removed": False}

        avatar = await auth_actions.set_avatar(session, user.id, None)

    await auth_actions.forget_avatar(AvatarsConnection.get(), avatar)

    return {"removed": avatar is not None}


async def delete_user_data(args: argparse.Namespace) -> object:
    session_factory = DatabaseSessions.get()
    async with session_factory() as session, session.begin():
        user_id = await auth_repositories.get_user_by_email(session, args.email)
        if user_id is None:
            logger.warning("[Data] No User With That Email")
            return {"deleted": False}

        avatar = None
        if args.account:
            avatar = await library_actions.delete_user(
                session,
                RedisConnection.get(),
                user_id,
            )
        else:
            await library_actions.clear_library(session, user_id, unlink=True)

    await auth_actions.forget_avatar(AvatarsConnection.get(), avatar)

    return {"deleted": True, "account": args.account}


JOBS: dict[str, Job] = {
    "delete_user_data": Job(
        run=delete_user_data,
        help="delete a user's library and linked apps, or with --account everything, "
        "regardless of DATA_DELETION_ENABLED",
        arguments=_arguments,
    ),
    "restore_playlist_songs": Job(
        run=restore_playlist_songs,
        help="bring back the playlist songs an app's import removed between two times, "
        "and send them to the linked apps again",
        arguments=_restore_arguments,
    ),
    "remove_avatar": Job(
        run=remove_avatar,
        help="take down a user's profile picture, from the database and the bucket",
        arguments=_avatar_arguments,
    ),
    "hide_lyrics": Job(
        run=hide_lyrics,
        help="hide a song's lyrics for everyone, until lrclib has other lyrics for it",
        arguments=_hide_arguments,
    ),
    "lyrics_reports": Job(
        run=lyrics_reports,
        help="list the lyrics people reported wrong, the most reported first",
        arguments=_reports_arguments,
    ),
    "push_keys": Job(
        run=push_keys,
        help="make a new pair of push notification keys for MESSAGES_PUSH_*, once",
    ),
    "user_reports": Job(
        run=user_reports,
        help="list the people others reported, the most reported first",
        arguments=_reports_arguments,
    ),
    "message_reports": Job(
        run=message_reports,
        help="list the messages people reported, the most reported first",
        arguments=_reports_arguments,
    ),
    "merge_tracks": Job(
        run=merge_tracks,
        help="merge the tracks saved twice for one song, and uppercase the isrcs",
        arguments=_merge_arguments,
    ),
}
