from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import Path
from fastapi import Query
from fastapi import Request
from fastapi import Response
from fastapi import status

from src.controllers import messages as messages_controller
from src.dependencies import DBSessionDep
from src.dependencies import MessageChangesDep
from src.dependencies import NowDep
from src.dependencies import RedisDep
from src.dependencies import SessionFactoryDep
from src.dependencies import UserIDDep
from src.dependencies import require_trusted_origin
from src.settings import settings
from src.structs.models import Page
from src.structs.models.requests import ConversationListRequest
from src.structs.models.requests import MessageListRequest
from src.structs.models.requests import MessagePeopleRequest
from src.structs.models.requests import PushRemovalRequest
from src.structs.models.requests import PushSubscriptionRequest
from src.structs.models.requests import ReactionRequest
from src.structs.models.requests import SendMessageRequest
from src.structs.models.responses import ChatMessage
from src.structs.models.responses import Conversation
from src.structs.models.responses import ConversationSummary
from src.structs.models.responses import MessagePerson
from src.structs.models.responses import MessageUpdates
from src.structs.models.responses import PushSettings
from src.structs.models.responses import StartedChat


router = APIRouter(prefix="/messages")
writes = [Depends(require_trusted_origin)]


@router.get("/updates")
async def updates(
    request: Request,
    response: Response,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    changes: MessageChangesDep,
    wait: Annotated[int, Query(ge=0, le=60)] = 0,
    seen: Annotated[str | None, Query(max_length=200)] = None,
    viewing: UUID | None = None,
) -> MessageUpdates:
    seen = seen or request.headers.get("if-none-match")
    read = await messages_controller.updates(
        session,
        redis,
        changes,
        user_id=user_id,
        seen=seen,
        wait=min(wait, settings.messages.longest_wait_seconds),
        viewing=viewing,
    )
    headers = {"ETag": read.tag, "Cache-Control": "private, no-cache"}
    if read.tag == seen:
        return Response(  # type: ignore[return-value]
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    response.headers.update(headers)

    return read


@router.get("/conversations")
async def list_conversations(
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[ConversationListRequest, Query()],
) -> Page[ConversationSummary]:
    return await messages_controller.list_conversations(
        session,
        request,
        user_id=user_id,
    )


@router.get("/people")
async def message_people(
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    request: Annotated[MessagePeopleRequest, Query()],
) -> list[MessagePerson]:
    return await messages_controller.message_people(
        session,
        redis,
        request.q,
        user_id=user_id,
    )


@router.post(
    "/with/{username}",
    status_code=status.HTTP_201_CREATED,
    dependencies=writes,
)
async def send_to(
    username: Annotated[str, Path(min_length=1, max_length=40)],
    body: SendMessageRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    background: BackgroundTasks,
    now: NowDep,
) -> StartedChat:
    started, members = await messages_controller.send_to(
        session,
        redis,
        username,
        body,
        user_id=user_id,
        now=now,
    )
    background.add_task(
        messages_controller.notify,
        session_factory,
        redis,
        started.conversation_id,
        started.message,
        sender_id=user_id,
        members=members,
    )

    return started


@router.get("/conversations/{conversation_id}")
async def read_conversation(
    conversation_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    request: Annotated[MessageListRequest, Query()],
) -> Conversation:
    return await messages_controller.read_conversation(
        session,
        conversation_id,
        request,
        user_id=user_id,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
    dependencies=writes,
)
async def send_message(
    conversation_id: UUID,
    body: SendMessageRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    background: BackgroundTasks,
    now: NowDep,
) -> ChatMessage:
    sent, members = await messages_controller.send_message(
        session,
        redis,
        conversation_id,
        body,
        user_id=user_id,
        now=now,
    )
    background.add_task(
        messages_controller.notify,
        session_factory,
        redis,
        conversation_id,
        sent,
        sender_id=user_id,
        members=members,
    )

    return sent


@router.post(
    "/conversations/{conversation_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def mark_read(
    conversation_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    now: NowDep,
) -> Response:
    await messages_controller.mark_read(
        session,
        redis,
        conversation_id,
        user_id=user_id,
        now=now,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/conversations/{conversation_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def unsend(
    conversation_id: UUID,
    message_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
    now: NowDep,
) -> Response:
    await messages_controller.unsend(
        session,
        redis,
        conversation_id,
        message_id,
        user_id=user_id,
        now=now,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/conversations/{conversation_id}/messages/{message_id}/reaction",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def react(
    conversation_id: UUID,
    message_id: UUID,
    body: ReactionRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    background: BackgroundTasks,
) -> Response:
    notify = await messages_controller.react(
        session,
        redis,
        conversation_id,
        message_id,
        user_id=user_id,
        emoji=body.emoji,
    )
    if notify is not None:
        background.add_task(
            messages_controller.notify_reaction,
            session_factory,
            redis,
            conversation_id,
            message_id,
            actor_id=user_id,
            recipient_id=notify,
            emoji=body.emoji,
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/conversations/{conversation_id}/messages/{message_id}/reaction",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def unreact(
    conversation_id: UUID,
    message_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> Response:
    await messages_controller.react(
        session,
        redis,
        conversation_id,
        message_id,
        user_id=user_id,
        emoji=None,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _block(
    conversation_id: UUID,
    user_id: UUID,
    session: DBSessionDep,
    redis: RedisDep,
    *,
    blocked: bool,
) -> Response:
    await messages_controller.set_blocked(
        session,
        redis,
        conversation_id,
        user_id=user_id,
        blocked=blocked,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/conversations/{conversation_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def block(
    conversation_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> Response:
    return await _block(conversation_id, user_id, session, redis, blocked=True)


@router.delete(
    "/conversations/{conversation_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def unblock(
    conversation_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> Response:
    return await _block(conversation_id, user_id, session, redis, blocked=False)


@router.post(
    "/{message_id}/report",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def report_message(
    message_id: UUID,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await messages_controller.report_message(session, message_id, user_id=user_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/push")
async def push_settings(_: UserIDDep) -> PushSettings:
    return messages_controller.push_settings()


@router.put(
    "/push",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def subscribe(
    body: PushSubscriptionRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await messages_controller.subscribe(session, body, user_id=user_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/push",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=writes,
)
async def unsubscribe(
    body: PushRemovalRequest,
    user_id: UserIDDep,
    session: DBSessionDep,
) -> Response:
    await messages_controller.unsubscribe(session, body, user_id=user_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
