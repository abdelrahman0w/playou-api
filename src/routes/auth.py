from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi import Response
from fastapi import status

from src.controllers import auth as auth_controller
from src.dependencies import ClientIPDep
from src.dependencies import DBSessionDep
from src.dependencies import NowDep
from src.dependencies import RedisDep
from src.dependencies import ResendDep
from src.dependencies import UserIDDep
from src.dependencies import get_session_token
from src.dependencies import require_trusted_origin
from src.settings import settings
from src.structs.enums import SessionTransports
from src.structs.models.requests import EmailCodeRequest
from src.structs.models.requests import EmailVerifyRequest
from src.structs.models.responses import AuthUser
from src.structs.models.responses import BearerSession
from src.structs.models.responses import EmailCodeSent


router = APIRouter(prefix="/auth")


def _set_session_cookie(
    response: Response,
    token: str,
) -> None:
    auth = settings.auth
    response.set_cookie(
        auth.cookie_name,
        token,
        max_age=auth.session_days * 24 * 60 * 60,
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post(
    "/email/code",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_trusted_origin)],
)
async def send_email_code(
    body: EmailCodeRequest,
    session: DBSessionDep,
    redis: RedisDep,
    resend: ResendDep,
    ip: ClientIPDep,
    now: NowDep,
) -> EmailCodeSent:
    return await auth_controller.send_email_code(
        session,
        redis,
        resend,
        body,
        ip=ip,
        now=now,
    )


@router.post(
    "/email/verify",
    dependencies=[Depends(require_trusted_origin)],
)
async def verify_email_code(
    body: EmailVerifyRequest,
    request: Request,
    response: Response,
    session: DBSessionDep,
    redis: RedisDep,
    ip: ClientIPDep,
    now: NowDep,
) -> AuthUser | BearerSession:
    user, token = await auth_controller.verify_email_code(
        session,
        redis,
        body,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        now=now,
    )

    if body.transport is SessionTransports.BEARER:
        return BearerSession(
            user=user,
            token=token,
            expires_in_seconds=settings.auth.session_days * 24 * 60 * 60,
        )

    _set_session_cookie(
        response,
        token,
    )

    return user


@router.post(
    "/sign-out",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def sign_out(
    request: Request,
    session: DBSessionDep,
    redis: RedisDep,
) -> Response:
    await auth_controller.sign_out(
        session,
        redis,
        get_session_token(request),
    )

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.auth.cookie_name,
        path="/",
        secure=settings.auth.cookie_secure,
        httponly=True,
        samesite="lax",
    )

    return response


@router.get("/me")
async def get_me(user_id: UserIDDep, session: DBSessionDep) -> AuthUser:
    return await auth_controller.get_me(session, user_id)
