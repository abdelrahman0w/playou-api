from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.providers import logger
from src.repositories import catalog as catalog_repositories
from src.settings import settings


async def merge_duplicates(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dry_run: bool,
) -> dict[str, int]:
    async with session_factory() as session:
        duplicates = await catalog_repositories.find_duplicates(
            session,
            across_scripts=settings.catalog.match_across_scripts,
        )

    for duplicate in duplicates:
        logger.info(
            "[Catalog] Duplicate Found",
            keep=str(duplicate.keep),
            drop=str(duplicate.drop),
            title=duplicate.title,
            duplicate_title=duplicate.duplicate_title,
        )
        if not dry_run:
            async with session_factory() as session, session.begin():
                await catalog_repositories.merge_track(
                    session,
                    duplicate.keep,
                    duplicate.drop,
                )

    uppercased = 0
    if not dry_run:
        async with session_factory() as session, session.begin():
            uppercased = await catalog_repositories.uppercase_isrcs(session)

    counts = {
        "merged": 0 if dry_run else len(duplicates),
        "found": len(duplicates),
        "uppercased": uppercased,
    }
    logger.info(
        "[Catalog] Duplicates Merged",
        dry_run=dry_run,
        **counts,
    )

    return counts
