import logging

from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Annotated
from pwdlib import PasswordHash
from sqlmodel import select

from src.db.db import session_dep
from src.db.models import User, UserPublic
from lib.auth.auth import verify_token, create_user, create_token
from lib.auth.models import Login, RegisterUser
from settings import settings

auth_router = APIRouter(prefix="/auth")
logger = logging.getLogger(__name__)

#@auth_router.post("/register")
#async def register(user: RegisterUser, session: session_dep) -> UserPublic:
#    return await create_user(session, user.username, user.email, user.password)

@auth_router.post("/token")
async def login(login: Login, session: session_dep):
    hash = PasswordHash.recommended()

    statement = select(User).where(User.username == login.username)
    result = await session.exec(statement)
    user = result.first()

    if not user or not hash.verify(login.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid Username or Password")

    return {"token": create_token(user.id)}

@auth_router.get("/user/me")
async def get_user(request: Request, session: session_dep, _: Annotated[None, Depends(verify_token)]) -> dict[str, UserPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    statement = select(User).where(User.id == user_id)
    result = await session.exec(statement)
    user = result.first()
    return {"user": UserPublic.model_validate(user)}