import jwt
import secrets
import string
import redis.asyncio as redis
import uuid

from settings import settings
from src.db.models import User, UserPublic
from lib.auth.enums import Role

from fastapi import HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from sqlmodel.ext.asyncio.session import AsyncSession
from pwdlib import PasswordHash
from datetime import datetime, timedelta, timezone

api_key_header = APIKeyHeader(name="X-API-KEY")
PASSWORD_RESET_REQUIRED_PREFIX = "auth:password_reset_required"
PASSWORD_RESET_TOKEN_PREFIX = "auth:password_reset_token"

def verify_token(request: Request, token: str = Depends(api_key_header)):
    token = token

    if not token:
        raise HTTPException(status_code=401, detail="No token provided")

    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        request.state.claims = claims
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def create_token(user_id: int, role: Role, expires_in: int | None = None) -> str:
    if expires_in is not None:
        expires_in = int(expires_in)
    else:
        expires_in = int(settings.DEFAULT_EXP_MINUTES)
    return jwt.encode({
        "id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in),
        "role": role.value
    }, settings.SECRET_KEY, algorithm="HS256")

def generate_password(length: int):
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    specials = "!@#$%^&*()-_=+[]{};:,.<>?/"

    all_chars = upper + lower + digits + specials
    password = [
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(specials),
    ]

    password += [secrets.choice(all_chars) for _ in range(length - 4)]

    secrets.SystemRandom().shuffle(password)
    return "".join(password)

def _password_reset_key(user_id: int) -> str:
    return f"{PASSWORD_RESET_REQUIRED_PREFIX}:{user_id}"

async def set_password_reset_required(user_id: int) -> None:
    if not settings.REDIS_URL:
        return
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.set(_password_reset_key(user_id), "1")
    finally:
        await client.aclose()

async def clear_password_reset_required(user_id: int) -> None:
    if not settings.REDIS_URL:
        return
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.delete(_password_reset_key(user_id))
    finally:
        await client.aclose()

async def password_reset_required(user_id: int) -> bool:
    if not settings.REDIS_URL:
        return False
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        value = await client.get(_password_reset_key(user_id))
        return value == "1"
    finally:
        await client.aclose()

async def reset_password(session: AsyncSession, user_id: int, new_password: str) -> None:
    pwhash = PasswordHash.recommended()
    password_hash = pwhash.hash(new_password)
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password = password_hash
    await session.commit()
    await clear_password_reset_required(user_id)

def _password_reset_token_key(token: str) -> str:
    return f"{PASSWORD_RESET_TOKEN_PREFIX}:{token}"

async def create_password_reset_token(user_id: int, ttl_seconds: int | None = None) -> str:
    if not settings.REDIS_URL:
        raise HTTPException(status_code=500, detail="Password reset token storage is not configured")

    token = str(uuid.uuid4())
    ttl = ttl_seconds if ttl_seconds is not None else max(60, int(settings.DEFAULT_EXP_MINUTES) * 60)
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.set(_password_reset_token_key(token), str(user_id), ex=ttl)
        return token
    finally:
        await client.aclose()

async def get_password_reset_token_user_id(token: str) -> int | None:
    if not settings.REDIS_URL:
        return None
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        value = await client.get(_password_reset_token_key(token))
        if value is None:
            return None
        return int(value)
    finally:
        await client.aclose()

async def delete_password_reset_token(token: str) -> None:
    if not settings.REDIS_URL:
        return
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.delete(_password_reset_token_key(token))
    finally:
        await client.aclose()

async def password_reset_token_valid(user_id: int, token: str) -> bool:
    token_user_id = await get_password_reset_token_user_id(token)
    return token_user_id == user_id

async def create_user(session: AsyncSession, username: str, email: str, password: str, role: Role = Role.USER) -> UserPublic:
    pwhash = PasswordHash.recommended()
    password_hash = pwhash.hash(password)
    user = User(username=username, email=email, password=password_hash, role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserPublic.model_validate(user)

def required_roles(roles: list[Role]):
    """FastAPI dependency factory. Use: Depends(required_roles([Role.ADMIN]))."""

    async def dependency(request: Request, _: None = Depends(verify_token)) -> None:
        claims = getattr(request.state, "claims", None)
        if not claims or "role" not in claims:
            raise HTTPException(status_code=401, detail="Missing JWT claims on request")

        allowed = {r.value for r in roles}
        if claims["role"] not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    return dependency