from pydantic import BaseModel

from src.structs.enums import CheckStatuses


class LivenessResponse(BaseModel):
    status: CheckStatuses = CheckStatuses.OK


class ReadinessResponse(BaseModel):
    status: CheckStatuses
    checks: dict[str, CheckStatuses]
