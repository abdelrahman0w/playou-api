import hashlib
import math
from dataclasses import asdict
from datetime import datetime
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

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
from src.services.resend.client import BATCH_SIZE as RESEND_BATCH_SIZE
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.models import ExpiringAccount
from src.structs.models import OutgoingEmail


def reconnect_url(
    platform: Platforms,
) -> str:
    query = urlencode({"reconnect": platform})

    return f"{settings.app.web_url.rstrip('/')}/accounts?{query}"


def _warning(
    item: ExpiringAccount,
    expires_at: datetime,
    *,
    now: datetime,
) -> OutgoingEmail:
    platform = item.account.platform
    email = reconnect_email(
        platform.title(),
        days=max(1, math.ceil((expires_at - now) / timedelta(days=1))),
        url=reconnect_url(platform),
        locale=item.owner.locale,
    )

    return OutgoingEmail(to=item.owner.email, **asdict(email))


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

    warnings: list[tuple[UUID, OutgoingEmail, str]] = []
    for item in expiring:
        account = item.account
        if account.refresh_expires_at is not None:
            warnings.append(
                (
                    account.id,
                    _warning(item, account.refresh_expires_at, now=now),
                    f"{account.id}:{account.refresh_expires_at.isoformat()}",
                ),
            )

    for start in range(0, len(warnings), RESEND_BATCH_SIZE):
        batch = warnings[start : start + RESEND_BATCH_SIZE]
        key = hashlib.blake2b(
            ",".join(sorted(expiry for _, _, expiry in batch)).encode(),
            digest_size=16,
        ).hexdigest()

        try:
            await resend.send_batch(
                [email for _, email, _ in batch],
                idempotency_key=f"reconnect-warnings-{key}",
            )
        except EmailUnavailableError as error:
            counts["warnings_failed"] += len(batch)
            logger.warning(
                "[Accounts] Warnings Failed",
                accounts=len(batch),
                error=error.message,
            )

            continue

        async with session_factory() as session, session.begin():
            await accounts_repositories.mark_warned(
                session,
                [account_id for account_id, _, _ in batch],
                now=now,
            )

        counts["warned"] += len(batch)

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
        accounts = await accounts_repositories.list_expiring_accounts(
            session,
            platforms=extendable,
            now=now,
            before=before,
            limit=accounts_settings.keep_alive_batch_size,
        )

    warnings = await warn_expiring_accounts(session_factory, resend, now=now)

    counts = {
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
