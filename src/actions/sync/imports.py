from collections.abc import Awaitable
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import accounts as accounts_actions
from src.actions.sync.push import fail_attempt
from src.exceptions import PlatformError
from src.exceptions import PlatformNotLinkedError
from src.exceptions import PlatformRateLimitedError
from src.exceptions import PlatformReconnectRequiredError
from src.exceptions import QuotaExhaustedError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import catalog as catalog_repositories
from src.repositories import library as library_repositories
from src.repositories import sync as sync_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import AccountStatuses
from src.structs.enums import ImportStatuses
from src.structs.enums import Platforms
from src.structs.enums import PlaylistImports
from src.structs.enums import PlaylistKinds
from src.structs.enums import RemovedBy
from src.structs.enums import SyncOutcomes
from src.structs.enums import SyncStatuses
from src.structs.enums import SyncSubjects
from src.structs.models import PlatformPlaylist
from src.structs.models import SavedTrack
from src.structs.models import StoredAccount
from src.structs.models import SyncTask
from src.structs.models.responses import AccountSync
from src.structs.models.responses import ImportProgress
from src.structs.models.responses import Progress


type OnPage = Callable[[int, int], Awaitable[None]]


class _Reporter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        task_id: int | None,
    ) -> None:
        self.session_factory = session_factory
        self.task_id = task_id
        self.progress = ImportProgress()

    async def report(self, **changes: Progress) -> None:
        if self.task_id is None:
            return

        self.progress = self.progress.model_copy(update=changes)
        async with self.session_factory() as session, session.begin():
            await sync_repositories.save_progress(
                session,
                self.task_id,
                self.progress.model_dump(mode="json"),
            )

    async def likes(self, done: int, total: int) -> None:
        await self.report(likes=Progress(done=done, total=total))


def _imports(platform: OAuthPlatform) -> bool:
    capabilities = platform.capabilities

    return capabilities.like or capabilities.playlists_read


async def _read_saved(
    platform: OAuthPlatform,
    token: str,
    *,
    stop_at: set[str] | None,
    on_page: OnPage,
) -> tuple[list[SavedTrack], int, bool]:
    saved: list[SavedTrack] = []
    total = 0
    cursor: str | None = None

    while True:
        page = await platform.saved_tracks(token, cursor=cursor)
        total = page.total
        for item in page.items:
            if stop_at is not None and item.track.platform_id in stop_at:
                return saved, total, False

            saved.append(item)

        if stop_at is None:
            await on_page(len(saved), total)
        if page.next is None or not page.items:
            return saved, total, True

        cursor = page.next


async def _import_likes(
    session_factory: async_sessionmaker[AsyncSession],
    platform: OAuthPlatform,
    account: StoredAccount,
    token: str,
    *,
    full: bool,
    now: datetime,
    reporter: _Reporter,
) -> tuple[bool, int]:
    async with session_factory() as session:
        known = await library_repositories.liked_platform_ids(
            session,
            account.user_id,
            account.platform,
        )

    saved, total, read_all = await _read_saved(
        platform,
        token,
        stop_at=None if full else set(known),
        on_page=reporter.likes,
    )
    if not read_all and (
        account.likes_total is None or total != account.likes_total + len(saved)
    ):
        saved, total, read_all = await _read_saved(
            platform,
            token,
            stop_at=None,
            on_page=reporter.likes,
        )

    kept = [item for item in saved if not item.ignored]
    async with session_factory() as session, session.begin():
        pending = await sync_repositories.pending_subject_ids(
            session,
            user_id=account.user_id,
            platform=account.platform,
            subject=SyncSubjects.LIKE,
        )
        catalog = await catalog_repositories.save_platform_tracks(
            session,
            [item.track for item in kept],
        )
        await library_repositories.import_likes(
            session,
            account.user_id,
            [
                (track.id, item.added_at or now)
                for track, item in zip(catalog, kept, strict=True)
                if track.id not in pending
            ],
            platform=account.platform,
        )

        if read_all:
            there = {track.id for track in catalog}
            await library_repositories.remove_likes(
                session,
                account.user_id,
                [
                    track_id
                    for track_id in set(known.values())
                    if track_id not in there and track_id not in pending
                ],
                now=now,
                removed_by=RemovedBy.PLATFORM,
            )

    return read_all, total


async def _import_playlists(
    session_factory: async_sessionmaker[AsyncSession],
    platform: OAuthPlatform,
    account: StoredAccount,
    token: str,
    *,
    now: datetime,
    reporter: _Reporter,
) -> None:
    remote = await platform.user_playlists(token)

    async with session_factory() as session:
        links = await library_repositories.platform_links(
            session,
            account.user_id,
            account.platform,
        )
        pending = await sync_repositories.pending_subject_ids(
            session,
            user_id=account.user_id,
            platform=account.platform,
            subject=SyncSubjects.PLAYLIST,
        )

    for done, playlist in enumerate(remote, start=1):
        owned = (
            playlist.owned
            if playlist.owned is not None
            else playlist.owner_id == account.external_id or playlist.collaborative
        )
        kind = PlaylistKinds.OWNED if owned else PlaylistKinds.FOLLOWED
        link = links.get(playlist.platform_id)
        if link is not None and link.playlist_id in pending:
            continue

        importing = link.importing if link is not None else PlaylistImports.AUTO
        unchanged = link is not None and link.snapshot_id == playlist.snapshot_id
        if importing is PlaylistImports.NEVER or (
            link is not None and link.skipped and unchanged
        ):
            continue

        changed = (
            link is None or link.removed or link.snapshot_id != playlist.snapshot_id
        )
        contents = (
            await platform.playlist_tracks(token, playlist.platform_id)
            if kind is PlaylistKinds.OWNED and changed
            else None
        )
        skipped = (
            contents is not None
            and not contents.music
            and importing is PlaylistImports.AUTO
        )

        async with session_factory() as session, session.begin():
            if link is None:
                playlist_id = await library_repositories.import_playlist(
                    session,
                    account.user_id,
                    account.platform,
                    playlist,
                    kind=kind,
                )
            else:
                playlist_id = link.playlist_id
                await library_repositories.update_from_platform(
                    session,
                    playlist_id,
                    playlist,
                    kind=kind,
                )

            if skipped:
                await library_repositories.skip_playlist(session, playlist_id, now=now)
            elif contents is not None:
                catalog = await catalog_repositories.save_platform_tracks(
                    session,
                    contents.tracks,
                )
                await library_repositories.reconcile_items(
                    session,
                    playlist_id,
                    [track.id for track in catalog],
                    now=now,
                )

            await library_repositories.save_link(
                session,
                playlist_id,
                account.platform,
                PlatformPlaylist(
                    platform_id=playlist.platform_id,
                    snapshot_id=playlist.snapshot_id,
                ),
            )

        if contents is not None:
            await reporter.report(playlists=Progress(done=done, total=len(remote)))

    there = {playlist.platform_id for playlist in remote}
    async with session_factory() as session, session.begin():
        await library_repositories.delete_playlists(
            session,
            [
                link.playlist_id
                for platform_id, link in links.items()
                if platform_id not in there and link.skipped
            ],
        )
        await library_repositories.remove_playlists(
            session,
            [
                link.playlist_id
                for platform_id, link in links.items()
                if platform_id not in there
                and not link.removed
                and link.playlist_id not in pending
            ],
            now=now,
            removed_by=RemovedBy.PLATFORM,
        )


async def import_account(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    account_id: UUID,
    *,
    now: datetime,
    task_id: int | None = None,
) -> SyncOutcomes:
    async with session_factory() as session:
        account = await accounts_repositories.get_account_by_id(session, account_id)

    if account is None:
        return SyncOutcomes.SKIPPED

    platform = platforms.get(account.platform)
    if platform is None or not _imports(platform):
        return SyncOutcomes.SKIPPED

    every = timedelta(hours=settings.imports.full_every_hours)
    full = account.likes_read_at is None or account.likes_read_at <= now - every
    reporter = _Reporter(session_factory, task_id)

    async def read(token: str) -> tuple[bool, int | None]:
        likes = (
            await _import_likes(
                session_factory,
                platform,
                account,
                token,
                full=full,
                now=now,
                reporter=reporter,
            )
            if platform.capabilities.like
            else (False, None)
        )
        if platform.capabilities.playlists_read:
            await _import_playlists(
                session_factory,
                platform,
                account,
                token,
                now=now,
                reporter=reporter,
            )

        return likes

    likes_read, likes_total = await accounts_actions.with_token(
        session_factory,
        platform,
        account,
        read,
        now=now,
    )

    async with session_factory() as session, session.begin():
        await accounts_repositories.mark_imported(
            session,
            account.id,
            now=now,
            likes_read=likes_read,
            likes_total=likes_total,
        )

    return SyncOutcomes.DONE


async def request_imports(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    now: datetime,
    stale_before: datetime | None = None,
) -> None:
    for account in await accounts_repositories.list_accounts(session, user_id):
        platform = platforms.get(account.platform)
        if platform is None or not _imports(platform):
            continue
        if account.status_at(now) is AccountStatuses.NEEDS_RECONNECT:
            continue
        if (
            stale_before is not None
            and account.imported_at is not None
            and account.imported_at > stale_before
        ):
            continue

        await sync_repositories.enqueue_import(
            session,
            user_id=user_id,
            platform=account.platform,
            account_id=account.id,
            now=now,
        )


async def library_sync(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
) -> list[AccountSync]:
    accounts = await accounts_repositories.list_accounts(session, user_id)
    latest = await sync_repositories.latest_imports(session, user_id)

    synced: list[AccountSync] = []
    for account in accounts:
        platform = platforms.get(account.platform)
        if platform is None or not _imports(platform):
            continue

        status, error, progress = latest.get(account.id, (None, None, None))
        syncing = status is SyncStatuses.PENDING
        synced.append(
            AccountSync(
                platform=account.platform,
                status=ImportStatuses.SYNCING
                if syncing
                else ImportStatuses.FAILED
                if status is SyncStatuses.FAILED
                else ImportStatuses.IDLE,
                imported_at=account.imported_at,
                error=error if status is not SyncStatuses.DONE else None,
                progress=ImportProgress.model_validate(progress)
                if syncing and progress
                else None,
            ),
        )

    return synced


async def _settle(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    task: SyncTask,
    *,
    now: datetime,
) -> SyncOutcomes | None:
    try:
        outcome = await import_account(
            session_factory,
            platforms,
            task.subject_id,
            now=now,
            task_id=task.id,
        )
    except PlatformReconnectRequiredError, PlatformNotLinkedError:
        async with session_factory() as session, session.begin():
            await sync_repositories.finish(
                session,
                task.id,
                SyncOutcomes.SKIPPED,
                now=now,
                error="The account has to be linked again",
            )

        return SyncOutcomes.SKIPPED
    except PlatformRateLimitedError as error:
        async with session_factory() as session, session.begin():
            await sync_repositories.retry_later(
                session,
                task.id,
                at=now + timedelta(seconds=error.retry_after_seconds),
                error=error.message,
                count_attempt=False,
            )

        return None
    except QuotaExhaustedError as error:
        async with session_factory() as session, session.begin():
            await sync_repositories.retry_later(
                session,
                task.id,
                at=error.retry_at,
                error=error.message,
                count_attempt=False,
            )

        return None
    except Exception as error:
        message = error.message if isinstance(error, PlatformError) else repr(error)
        if not isinstance(error, PlatformError):
            logger.exception(
                "[Imports] Import Crashed",
                exc_info=error,
                operation_id=task.id,
            )

        async with session_factory() as session, session.begin():
            return await fail_attempt(session, task, message, now=now)

    async with session_factory() as session, session.begin():
        await sync_repositories.finish(session, task.id, outcome, now=now)

    return outcome


async def import_user(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session_factory() as session, session.begin():
        tasks = await sync_repositories.lease_imports(
            session,
            now=now,
            until=now + timedelta(minutes=settings.imports.lease_minutes),
            limit=settings.imports.batch_size,
            user_id=user_id,
        )

    for task in tasks:
        await _settle(session_factory, platforms, task, now=now)


async def run_imports(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    *,
    now: datetime,
) -> dict[str, int]:
    imports = settings.imports

    async with session_factory() as session, session.begin():
        due = await accounts_repositories.list_accounts_to_import(
            session,
            platforms=[
                name for name, platform in platforms.items() if _imports(platform)
            ],
            now=now,
            before=now - timedelta(minutes=imports.every_minutes),
            limit=imports.batch_size,
        )
        for account in due:
            await sync_repositories.enqueue_import(
                session,
                user_id=account.user_id,
                platform=account.platform,
                account_id=account.id,
                now=now,
            )

        tasks = await sync_repositories.lease_imports(
            session,
            now=now,
            until=now + timedelta(minutes=imports.lease_minutes),
            limit=imports.batch_size,
        )

    counts = {"scheduled": len(due), "pending": 0} | {
        outcome.lower(): 0 for outcome in SyncOutcomes
    }
    for task in tasks:
        outcome = await _settle(session_factory, platforms, task, now=now)
        counts[outcome.lower() if outcome is not None else "pending"] += 1

    if tasks or due:
        logger.info(
            "[Imports] Imported",
            **counts,
        )

    return counts
