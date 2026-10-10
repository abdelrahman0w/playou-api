import hashlib
import hmac
import secrets
from datetime import datetime
from datetime import timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import rate_limit as rate_limit_actions
from src.actions.auth.emails import code_email
from src.exceptions import EmailUnavailableError
from src.exceptions import InvalidCodeError
from src.exceptions import NameRequiredError
from src.exceptions import TooManyRequestsError
from src.providers import logger
from src.repositories import auth as auth_repositories
from src.services import ResendService
from src.settings import Environment
from src.settings import settings
from src.structs.enums import CacheKeys
from src.structs.models.responses import AuthUser
from src.structs.models.responses import EmailCodeSent


HOUR = 60 * 60

_FALLBACK_SECRET = secrets.token_bytes(32)


def _secret() -> bytes:
    secret = settings.auth.secret

    return secret.get_secret_value().encode() if secret else _FALLBACK_SECRET


def code_hash(
    email: str,
    code: str,
) -> str:
    return hmac.new(
        _secret(),
        f"{email}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def _limit(
    redis: Redis,
    key: str,
    *,
    limit: int,
    message: str,
) -> None:
    result = await rate_limit_actions.hit(redis, key, limit=limit, window_seconds=HOUR)
    if not result.allowed:
        raise TooManyRequestsError(message, retry_after_seconds=result.reset)


async def send_email_code(
    session: AsyncSession,
    redis: Redis,
    resend: ResendService | None,
    *,
    email: str,
    locale: str,
    ip: str | None,
    now: datetime,
) -> EmailCodeSent:
    auth = settings.auth
    cooldown = CacheKeys.AUTH_CODE_COOLDOWN.format(email=email)

    try:
        if not await redis.set(
            cooldown,
            1,
            nx=True,
            ex=auth.code_cooldown_seconds,
        ):
            left = await redis.ttl(cooldown)

            raise TooManyRequestsError(
                "A code was just sent, wait before asking for another",
                retry_after_seconds=max(1, left),
            )
    except RedisError:
        logger.warning(
            "[Auth] Code Cooldown Skipped - Redis Is Unavailable",
        )

    await _limit(
        redis,
        f"auth-codes-email:{email}",
        limit=auth.codes_per_email_hour,
        message="Too many codes were sent to this address, try again later",
    )
    if ip is not None:
        await _limit(
            redis,
            f"auth-codes-ip:{ip}",
            limit=auth.codes_per_ip_hour,
            message="Too many codes were asked for, try again later",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    async with session.begin():
        await auth_repositories.replace_email_code(
            session,
            email,
            code_hash=code_hash(email, code),
            expires_at=now + timedelta(minutes=auth.code_minutes),
            now=now,
        )

    message = code_email(
        code,
        locale=locale,
        minutes=auth.code_minutes,
    )
    if resend is not None:
        await resend.send(
            email, subject=message.subject, html=message.html, text=message.text
        )
    elif settings.app.environment is Environment.DEV:
        logger.warning(
            "[Auth] Code Not Sent - No Resend Key",
            email=email,
            code=code,
        )
    else:
        raise EmailUnavailableError("Codes cannot be sent right now")

    return EmailCodeSent(
        expires_in_seconds=auth.code_minutes * 60,
        resend_in_seconds=auth.code_cooldown_seconds,
    )


async def verify_email_code(
    session: AsyncSession,
    *,
    redis: Redis,
    email: str,
    code: str,
    locale: str,
    ip: str | None,
    now: datetime,
    name: str | None = None,
) -> tuple[AuthUser, bool]:
    auth = settings.auth
    if ip is not None:
        await _limit(
            redis,
            f"auth-verify-ip:{ip}",
            limit=auth.verifications_per_ip_hour,
            message="Too many codes were tried, try again later",
        )

    wrong: str | None = None
    async with session.begin():
        live = await auth_repositories.get_live_code(
            session,
            email,
            now=now,
        )
        if live is None or live.attempts >= auth.code_attempts:
            raise InvalidCodeError("The code has expired, ask for a new one")

        if hmac.compare_digest(live.code_hash, code_hash(email, code)):
            if name is None:
                signed_in = await auth_repositories.touch_user(session, email, now=now)
                if signed_in is None:
                    raise NameRequiredError("Tell us your name to finish signing up")
                user, created = signed_in, False
            else:
                user, created = await auth_repositories.sign_in_user(
                    session,
                    email,
                    locale=locale,
                    now=now,
                    name=name,
                )
            live.consumed_at = now
        else:
            live.attempts += 1
            left = auth.code_attempts - live.attempts
            wrong = (
                f"The code is wrong, {left} tries left"
                if left
                else "The code is wrong, ask for a new one"
            )

    if wrong is not None:
        raise InvalidCodeError(wrong)

    return user, created
