from enum import StrEnum


class CacheKeys(StrEnum):
    RATE_LIMIT = "ratelimit:{client}"
    AUTH_SESSION = "auth:session:{token}"
    AUTH_CODE_COOLDOWN = "auth:code-cooldown:{email}"
    ACCOUNTS_LINK = "accounts:link:{state}"
    CATALOG_SEARCH = "catalog:search:{platform}:{account_id}"
    CATALOG_SEARCH_SHARED = "catalog:search:{platform}"
    PLATFORM_PAUSED = "platform:{platform}:paused"
    PLATFORM_QUOTA = "platform:{platform}:quota:{day}"
