import math
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import NameChangeLimitedError
from src.exceptions import UnauthorizedError
from src.exceptions import UsernameTakenError
from src.repositories import auth as auth_repositories
from src.repositories import people as people_repositories
from src.settings import settings
from src.structs.enums import NameFields
from src.structs.models.responses import AuthUser


USERNAME_INDEX = "uq_users_username"


@contextmanager
def username_collisions() -> Generator[None]:
    try:
        yield
    except IntegrityError as exc:
        if USERNAME_INDEX in str(exc.orig):
            raise UsernameTakenError("That username is taken") from exc

        raise


async def _changes(
    session: AsyncSession,
    user_id: UUID,
    field: NameFields,
    *,
    now: datetime,
) -> tuple[int, datetime | None]:
    allowed = settings.auth.name_changes
    window = timedelta(days=settings.auth.name_change_days)
    changes = await auth_repositories.name_changes_since(
        session,
        user_id,
        since=now - window,
        field=field,
    )
    left = max(0, allowed - len(changes))

    return left, changes[len(changes) - allowed] + window if left == 0 else None


async def with_name_limits(
    session: AsyncSession,
    user: AuthUser,
    *,
    now: datetime,
) -> AuthUser:
    names_left, name_at = await _changes(session, user.id, NameFields.NAME, now=now)
    usernames_left, username_at = await _changes(
        session,
        user.id,
        NameFields.USERNAME,
        now=now,
    )

    return user.model_copy(
        update={
            "name_changes_left": names_left,
            "name_change_at": name_at,
            "username_changes_left": usernames_left,
            "username_change_at": username_at,
        },
    )


async def _limited(
    session: AsyncSession,
    user_id: UUID,
    field: NameFields,
    *,
    now: datetime,
) -> None:
    _, frees_at = await _changes(session, user_id, field, now=now)
    if frees_at is None:
        return

    what = "name" if field == NameFields.NAME else "username"
    raise NameChangeLimitedError(
        f"Your {what} was changed too many times lately, "
        f"it can change again on {frees_at.date().isoformat()}",
        retry_after_seconds=max(1, math.ceil((frees_at - now).total_seconds())),
    )


async def _locked(session: AsyncSession, user_id: UUID) -> AuthUser:
    user = await auth_repositories.lock_user(session, user_id)
    if user is None:
        raise UnauthorizedError("Sign in to continue")

    return user


async def change_name(
    session: AsyncSession,
    user_id: UUID,
    name: str,
    *,
    now: datetime,
) -> AuthUser:
    user = await _locked(session, user_id)
    if user.name == name:
        return user

    await _limited(session, user_id, NameFields.NAME, now=now)
    await auth_repositories.record_name_change(session, user_id, now=now)

    return await auth_repositories.update_user(session, user_id, name=name)


async def change_username(
    session: AsyncSession,
    user_id: UUID,
    username: str,
    *,
    now: datetime,
) -> AuthUser:
    user = await _locked(session, user_id)
    if user.username.lower() == username:
        return user
    if await people_repositories.username_taken(
        session,
        username,
        except_user=user_id,
    ):
        raise UsernameTakenError("That username is taken")

    await _limited(session, user_id, NameFields.USERNAME, now=now)
    await auth_repositories.record_name_change(
        session,
        user_id,
        now=now,
        field=NameFields.USERNAME,
    )

    with username_collisions():
        return await auth_repositories.update_user(
            session,
            user_id,
            username=username,
        )
