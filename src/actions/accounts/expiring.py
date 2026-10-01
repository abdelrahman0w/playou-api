import math
from datetime import datetime
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions.accounts import tokens as tokens_actions
from src.actions.accounts.emails import reconnect_email
from src.exceptions import EmailUnavailableError
from src.exceptions import PlatformError
from src.exceptions import PlatformNotLinkedError
from src.exceptions import PlatformReconnectRequiredError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.services import OAuthPlatform
from src.services import ResendService
from src.settings import settings
from src.structs.enums import Platforms


def _reconnect_url(
    platform: Platforms,
) -> str:
    query = urlencode({"reconnect": platform})

    return f"{settings.app.web_url.rstrip('/')}/accounts?{query}"


async def warn_expiring_accounts(
    session_factory: async_sessionmaker[AsyncSession],
    resend: ResendService | None,
    *,
    now: datetime,
) -> dict[str, int]:
    accounts_settings = settings.accounts
    counts = {"warned": 0, "warnings_failed": 0}

    if resend is None:
        logger.warning(
            "[Accounts] Warnings Skipped - No Resend Key",
        )

        return counts

    async with session_factory() as session:
        expiring = await accounts_repositories.list_accounts_to_warn(
            session,
            now=now,
            before=now + timedelta(days=accounts_settings.expiry_warning_days),
            limit=accounts_settings.keep_alive_batch_size,
        )

    for item in expiring:
        account = item.account
        if account.refresh_expires_at is None:
            continue

        email = reconnect_email(
            account.platform.title(),
            days=max(
                1, math.ceil((account.refresh_expires_at - now) / timedelta(days=1))
            ),
            url=_reconnect_url(account.platform),
            locale=item.owner.locale,
        )

        try:
            await resend.send(
                item.owner.email,
                subject=email.subject,
                html=email.html,
                text=email.text,
            )
        except EmailUnavailableError as error:
            counts["warnings_failed"] += 1

            logger.warning(
                "[Accounts] Warning Failed",
                platform=account.platform,
                account_id=str(account.id),
                error=error.message,
            )

            continue

        async with session_factory() as session, session.begin():
            await accounts_repositories.mark_warned(session, account.id, now=now)

        counts["warned"] += 1

    return counts


async def check_expiring_accounts(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    resend: ResendService | None,
    *,
    now: datetime,
) -> dict[str, int]:
    accounts_settings = settings.accounts
    before = now + timedelta(days=accounts_settings.keep_alive_days)
    extendable = [
        name
        for name, platform in platforms.items()
        if platform.refresh_extends_lifetime
    ]

    async with session_factory() as session:
        async with session.begin():
            expired = await accounts_repositories.mark_expired_accounts(
                session,
                now=now,
            )

        accounts = await accounts_repositories.list_expiring_accounts(
            session,
            platforms=extendable,
            before=before,
            limit=accounts_settings.keep_alive_batch_size,
        )

    warnings = await warn_expiring_accounts(session_factory, resend, now=now)

    counts = {
        "expired": expired,
        **warnings,
        "due": len(accounts),
        "refreshed": 0,
        "skipped": 0,
        "needs_reconnect": 0,
        "failed": 0,
    }

    for account in accounts:
        try:
            refreshed = await tokens_actions.keep_alive(
                session_factory,
                platforms[account.platform],
                account,
                now=now,
                before=before,
            )
        except PlatformReconnectRequiredError, PlatformNotLinkedError:
            counts["needs_reconnect"] += 1
        except PlatformError as error:
            counts["failed"] += 1
            logger.warning(
                "[Accounts] Keep Alive Failed",
                platform=account.platform,
                account_id=str(account.id),
                error=error.message,
            )
        else:
            counts["refreshed" if refreshed else "skipped"] += 1

    logger.info(
        "[Accounts] Checked The Expiring Accounts",
        **counts,
    )

    return counts
