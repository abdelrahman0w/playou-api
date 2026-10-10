import math
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import NameChangeLimitedError
from src.exceptions import UnauthorizedError
from src.repositories import auth as auth_repositories
from src.settings import settings
from src.structs.models.responses import AuthUser


async def with_name_limits(
    session: AsyncSession,
    user: AuthUser,
    *,
    now: datetime,
) -> AuthUser:
    allowed = settings.auth.name_changes
    window = timedelta(days=settings.auth.name_change_days)
    changes = await auth_repositories.name_changes_since(
        session,
        user.id,
        since=now - window,
    )
    left = max(0, allowed - len(changes))

    return user.model_copy(
        update={
            "name_changes_left": left,
            "name_change_at": changes[len(changes) - allowed] + window
            if left == 0
            else None,
        },
    )


async def change_name(
    session: AsyncSession,
    user_id: UUID,
    name: str,
    *,
    now: datetime,
) -> AuthUser:
    user = await auth_repositories.lock_user(session, user_id)
    if user is None:
        raise UnauthorizedError("Sign in to continue")
    if user.name == name:
        return await with_name_limits(session, user, now=now)

    limited = await with_name_limits(session, user, now=now)
    if limited.name_change_at is not None:
        raise NameChangeLimitedError(
            "Your name was changed too many times lately, "
            f"it can change again on {limited.name_change_at.date().isoformat()}",
            retry_after_seconds=max(
                1,
                math.ceil((limited.name_change_at - now).total_seconds()),
            ),
        )

    await auth_repositories.record_name_change(session, user_id, now=now)
    renamed = await auth_repositories.set_name(session, user_id, name)

    return await with_name_limits(session, renamed, now=now)
