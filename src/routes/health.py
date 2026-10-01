from fastapi import APIRouter
from fastapi import Response
from fastapi import status

from src.controllers import health as health_controller
from src.dependencies import DBSessionDep
from src.dependencies import RedisDep
from src.structs.enums import CheckStatuses
from src.structs.models.responses import LivenessResponse
from src.structs.models.responses import ReadinessResponse


router = APIRouter(prefix="/health")


@router.get("/live")
async def get_liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get("/ready")
async def get_readiness(
    session: DBSessionDep,
    redis: RedisDep,
    response: Response,
) -> ReadinessResponse:
    readiness = await health_controller.check_readiness(
        session,
        redis,
    )
    if readiness.status is not CheckStatuses.OK:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return readiness
