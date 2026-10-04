import secrets
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions.accounts.sealing import seal
from src.exceptions import InvalidOAuthStateError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import sync as sync_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import CacheKeys
from src.structs.models import PendingLink
from src.structs.models import PlatformTokens
from src.structs.models import StoredAccount
from src.utils import challenge_for
from src.utils import make_verifier


def expires_at(
    tokens: PlatformTokens,
    *,
    now: datetime,
) -> datetime | None:
    if tokens.expires_in_seconds is None:
        return None

    return now + timedelta(seconds=tokens.expires_in_seconds)


def refresh_expires_at(
    platform: OAuthPlatform,
    tokens: PlatformTokens,
    *,
    now: datetime,
) -> datetime | None:
    if tokens.refresh_token is None:
        return None

    if tokens.refresh_expires_in_seconds is not None:
        return now + timedelta(seconds=tokens.refresh_expires_in_seconds)

    lifetime = platform.refresh_token_lifetime

    return now + lifetime if lifetime is not None else None


async def start_link(
    redis: Redis,
    platform: OAuthPlatform,
    *,
    user_id: UUID,
) -> str:
    state = secrets.token_urlsafe(32)
    verifier = make_verifier()

    await redis.set(
        CacheKeys.ACCOUNTS_LINK.format(state=state),
        PendingLink(
            user_id=user_id,
            platform=platform.platform,
            verifier=verifier,
        ).model_dump_json(),
        ex=settings.accounts.link_minutes * 60,
    )

    return platform.authorize_url(state=state, challenge=challenge_for(verifier))


async def finish_link(
    session: AsyncSession,
    redis: Redis,
    platform: OAuthPlatform,
    *,
    user_id: UUID,
    code: str,
    state: str,
    now: datetime,
) -> StoredAccount:
    pending = await redis.getdel(CacheKeys.ACCOUNTS_LINK.format(state=state))
    if pending is None:
        raise InvalidOAuthStateError("The link expired, start again")

    link = PendingLink.model_validate_json(pending)
    if link.user_id != user_id or link.platform != platform.platform:
        raise InvalidOAuthStateError("The link was started by someone else")

    tokens = await platform.exchange_code(code, verifier=link.verifier)
    profile = await platform.profile(tokens.access_token.get_secret_value())
    refresh_token = tokens.refresh_token

    async with session.begin():
        account = await accounts_repositories.upsert_account(
            session,
            user_id=user_id,
            platform=platform.platform,
            external_id=profile.external_id,
            display_name=profile.display_name,
            access_token=seal(tokens.access_token.get_secret_value()),
            refresh_token=seal(refresh_token.get_secret_value())
            if refresh_token
            else None,
            expires_at=expires_at(tokens, now=now),
            refresh_expires_at=refresh_expires_at(platform, tokens, now=now),
            scopes=tokens.scopes,
            push_by_default=platform.capabilities.push_by_default,
        )
        await sync_repositories.enqueue_import(
            session,
            user_id=user_id,
            platform=platform.platform,
            account_id=account.id,
            now=now,
        )

    logger.info(
        "[Accounts] Linked",
        platform=platform.platform,
        account_id=str(account.id),
    )

    return account
