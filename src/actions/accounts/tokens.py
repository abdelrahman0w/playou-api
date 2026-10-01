from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions.accounts.oauth import expires_at
from src.actions.accounts.oauth import refresh_expires_at
from src.actions.accounts.sealing import seal
from src.actions.accounts.sealing import unseal
from src.exceptions import PlatformNotLinkedError
from src.exceptions import PlatformReconnectRequiredError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import AccountStatuses
from src.structs.models import PlatformTokens
from src.structs.models import StoredAccount


@dataclass(frozen=True)
class _Refreshed:
    access_token: str | None = None
    refreshed: bool = False
    reconnect: PlatformReconnectRequiredError | None = None


def _is_fresh(
    account: StoredAccount,
    *,
    now: datetime,
) -> bool:
    if account.expires_at is None:
        return True

    margin = timedelta(seconds=settings.accounts.refresh_margin_seconds)

    return account.expires_at - margin > now


def _next_refresh_expiry(
    platform: OAuthPlatform,
    tokens: PlatformTokens,
    locked: StoredAccount,
    *,
    now: datetime,
) -> datetime | None:
    if tokens.refresh_expires_in_seconds is not None:
        return now + timedelta(seconds=tokens.refresh_expires_in_seconds)

    if tokens.refresh_token is not None and platform.refresh_extends_lifetime:
        return refresh_expires_at(platform, tokens, now=now)

    return locked.refresh_expires_at


async def access_token(
    session_factory: async_sessionmaker[AsyncSession],
    platform: OAuthPlatform,
    account: StoredAccount,
    *,
    now: datetime,
) -> str:
    if account.status is AccountStatuses.NEEDS_RECONNECT:
        raise PlatformReconnectRequiredError("The account has to be linked again")

    if _is_fresh(account, now=now):
        return unseal(account.access_token)

    refreshed = await _refresh_when_due(
        session_factory,
        platform,
        account,
        now=now,
        is_due=lambda locked: not _is_fresh(locked, now=now),
    )
    if refreshed.access_token is None:
        raise PlatformReconnectRequiredError("The account has to be linked again")

    return refreshed.access_token


async def keep_alive(
    session_factory: async_sessionmaker[AsyncSession],
    platform: OAuthPlatform,
    account: StoredAccount,
    *,
    now: datetime,
    before: datetime,
) -> bool:
    def is_due(locked: StoredAccount) -> bool:
        return (
            locked.refresh_expires_at is not None
            and locked.refresh_expires_at <= before
        )

    refreshed = await _refresh_when_due(
        session_factory,
        platform,
        account,
        now=now,
        is_due=is_due,
    )

    return refreshed.refreshed


async def _refresh_when_due(
    session_factory: async_sessionmaker[AsyncSession],
    platform: OAuthPlatform,
    account: StoredAccount,
    *,
    now: datetime,
    is_due: Callable[[StoredAccount], bool],
) -> _Refreshed:
    async with session_factory() as session:
        async with session.begin():
            refreshed = await _refresh(
                session,
                platform,
                account,
                now=now,
                is_due=is_due,
            )

        if refreshed.reconnect is not None:
            async with session.begin():
                await accounts_repositories.set_status(
                    session,
                    account.id,
                    AccountStatuses.NEEDS_RECONNECT,
                )

            logger.warning(
                "[Accounts] Needs Reconnecting - The Refresh Was Refused",
                platform=account.platform,
                account_id=str(account.id),
            )

            raise refreshed.reconnect

    return refreshed


async def _refresh(
    session: AsyncSession,
    platform: OAuthPlatform,
    account: StoredAccount,
    *,
    now: datetime,
    is_due: Callable[[StoredAccount], bool],
) -> _Refreshed:
    locked = await accounts_repositories.get_account_by_id(
        session,
        account.id,
        for_update=True,
    )
    if locked is None:
        raise PlatformNotLinkedError(
            "The account is no longer linked",
        )

    if not is_due(locked):
        return _Refreshed(
            access_token=unseal(locked.access_token),
        )

    if locked.refresh_token is None:
        return _Refreshed(
            reconnect=PlatformReconnectRequiredError(
                "The account has to be linked again",
            ),
        )

    try:
        tokens = await platform.refresh(unseal(locked.refresh_token))
    except PlatformReconnectRequiredError as exc:
        return _Refreshed(reconnect=exc)

    rotated = tokens.refresh_token
    await accounts_repositories.update_tokens(
        session,
        locked.id,
        access_token=seal(tokens.access_token.get_secret_value()),
        refresh_token=seal(rotated.get_secret_value())
        if rotated
        else locked.refresh_token,
        expires_at=expires_at(tokens, now=now),
        refresh_expires_at=_next_refresh_expiry(platform, tokens, locked, now=now),
    )

    return _Refreshed(
        access_token=tokens.access_token.get_secret_value(),
        refreshed=True,
    )
