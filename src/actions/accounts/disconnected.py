import hashlib
from dataclasses import asdict
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions.accounts.emails import disconnected_email
from src.actions.accounts.expiring import reconnect_url
from src.exceptions import EmailUnavailableError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.services import ResendService
from src.services.resend.client import BATCH_SIZE as RESEND_BATCH_SIZE
from src.settings import settings
from src.structs.models import ExpiringAccount
from src.structs.models import OutgoingEmail


def _warning(
    item: ExpiringAccount,
) -> OutgoingEmail:
    platform = item.account.platform
    email = disconnected_email(
        platform.title(),
        url=reconnect_url(platform),
        locale=item.owner.locale,
    )

    return OutgoingEmail(to=item.owner.email, **asdict(email))


async def warn_disconnected_accounts(
    session_factory: async_sessionmaker[AsyncSession],
    resend: ResendService | None,
    *,
    now: datetime,
) -> dict[str, int]:
    counts = {"warned": 0, "failed": 0}

    if resend is None:
        logger.warning(
            "[Accounts] Disconnect Warnings Skipped - No Resend Key",
        )

        return counts

    async with session_factory() as session:
        disconnected = await accounts_repositories.list_disconnected_to_warn(
            session,
            limit=settings.accounts.keep_alive_batch_size,
        )

    for start in range(0, len(disconnected), RESEND_BATCH_SIZE):
        batch = disconnected[start : start + RESEND_BATCH_SIZE]
        key = hashlib.blake2b(
            ",".join(
                sorted(
                    f"{item.account.id}:{item.account.reconnect_required_at}"
                    for item in batch
                ),
            ).encode(),
            digest_size=16,
        ).hexdigest()

        try:
            await resend.send_batch(
                [_warning(item) for item in batch],
                idempotency_key=f"disconnect-warnings-{key}",
            )
        except EmailUnavailableError as error:
            counts["failed"] += len(batch)
            logger.warning(
                "[Accounts] Disconnect Warnings Failed",
                accounts=len(batch),
                error=error.message,
            )

            continue

        async with session_factory() as session, session.begin():
            await accounts_repositories.mark_disconnect_warned(
                session,
                [item.account.id for item in batch],
                now=now,
            )

        counts["warned"] += len(batch)

    if disconnected:
        logger.info(
            "[Accounts] Warned The Disconnected Accounts",
            **counts,
        )

    return counts
