import logging

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import func
from sqlmodel import select

from src.db.db import session_dep
from src.db.models import Message, MessagePublic, Stack
from lib.auth.auth import verify_token

from lib.message.models import MessageHistory, MessageHistoryResponse

message_router = APIRouter(prefix="/message", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)

@message_router.post("/history")
async def get_message_history(request: Request, body: MessageHistory, session: session_dep) -> MessageHistoryResponse:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    stack_stmt = select(Stack).where(Stack.id == body.stack_id, Stack.user_id == user_id)
    stack = (await session.exec(stack_stmt)).first()
    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    count_stmt = select(func.count(Message.id)).where(Message.stack_id == body.stack_id)
    if body.last_position is not None:
        count_stmt = count_stmt.where(Message.position >= body.last_position)
    total = await session.scalar(count_stmt)

    statement = select(Message).where(Message.stack_id == body.stack_id).order_by(Message.position.desc())
    if body.offset is not None:
        statement = statement.offset(body.offset)
    if body.last_position is not None:
        statement = statement.where(Message.position >= body.last_position)
    if body.limit is not None:
        statement = statement.limit(body.limit)

    result = await session.exec(statement)
    messages = list(reversed(result.all()))
    last_position = messages[-1].position if messages else -1
    limit = body.limit if body.limit is not None else 50
    offset = body.offset if body.offset is not None else 0
    more = total > limit * (offset + 1)

    return MessageHistoryResponse(messages=[MessagePublic.model_validate(message) for message in messages], total=total, last_position=last_position, more=more)
