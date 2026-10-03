from datetime import datetime
from datetime import timedelta

from pydantic import BaseModel

from src.structs.enums import AccountStatuses
from src.structs.enums import Platforms
from src.structs.models.platforms import Capabilities
from src.structs.models.platforms import StoredAccount


class LinkedAccount(BaseModel):
    platform: Platforms
    status: AccountStatuses
    display_name: str | None = None
    capabilities: Capabilities
    linked_at: datetime
    refresh_expires_at: datetime | None = None
    expires_soon: bool = False

    @classmethod
    def from_stored(
        cls,
        account: StoredAccount,
        capabilities: Capabilities,
        *,
        now: datetime,
        warn_within: timedelta,
    ) -> LinkedAccount:
        status = account.status_at(now)
        expires_at = account.refresh_expires_at

        return cls(
            platform=account.platform,
            status=status,
            expires_soon=status is AccountStatuses.ACTIVE
            and expires_at is not None
            and expires_at - now <= warn_within,
            display_name=account.display_name,
            capabilities=capabilities,
            linked_at=account.created_at,
            refresh_expires_at=account.refresh_expires_at,
        )
