from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories import auth as auth_repositories
from src.repositories import library as library_repositories
from src.settings import settings
from src.structs.enums import TogetherEffects
from src.structs.models.responses import TogetherTracks


async def together_tracks(session: AsyncSession, user_id: UUID) -> TogetherTracks:
    together = settings.together
    if not together.groups or not together.reasons:
        return TogetherTracks()

    user = await auth_repositories.get_user(session, user_id)
    email = user.email.casefold() if user is not None else None
    groups = [group for group in together.groups if email in group.emails]
    if not groups:
        return TogetherTracks()

    ids = await library_repositories.user_ids_by_email(
        session,
        {other for group in groups for other in group.emails if other != email},
    )
    tracks: dict[UUID, TogetherEffects] = {}
    for group in groups:
        others = [ids[other] for other in group.emails if other in ids]
        if not others:
            continue

        found = await library_repositories.together_track_ids(
            session,
            user_id,
            others,
            reasons=together.reasons,
        )
        for track_id in found:
            tracks.setdefault(track_id, group.effect)

    return TogetherTracks(tracks=tracks)
