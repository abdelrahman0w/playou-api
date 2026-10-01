from datetime import datetime

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

    @classmethod
    def from_stored(
        cls,
        account: StoredAccount,
        capabilities: Capabilities,
    ) -> LinkedAccount:
        return cls(
            platform=account.platform,
            status=account.status,
            display_name=account.display_name,
            capabilities=capabilities,
            linked_at=account.created_at,
            refresh_expires_at=account.refresh_expires_at,
        )
