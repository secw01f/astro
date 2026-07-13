import jwt
import asyncio
import hashlib
import secrets
import string
import redis.asyncio as redis

from settings import settings
from src.db.models import User, UserPublic
from src.db.db import session_dep
from lib.auth.enums import Role

from fastapi import HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from sqlmodel.ext.asyncio.session import AsyncSession
from pwdlib import PasswordHash
from datetime import datetime, timedelta, timezone

api_key_header = APIKeyHeader(name="X-API-KEY")
PASSWORD_RESET_TOKEN_PREFIX = "auth:password_reset_token"
PASSWORD_RESET_ATTEMPT_PREFIX = "auth:password_reset_attempts"


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters")
    checks = (
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(c in string.punctuation for c in password),
    )
    if not all(checks):
        raise HTTPException(
            status_code=422,
            detail="Password must include lowercase, uppercase, number, and symbol characters",
        )

async def verify_token(request: Request, session: session_dep, token: str = Depends(api_key_header)):
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")

    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=["HS256"],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = claims.get("id")
    token_version = claims.get("token_version")
    if user_id is None or token_version is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await session.get(User, int(user_id))
    if not user or not user.enabled:
        raise HTTPException(status_code=401, detail="Invalid token")
    if int(token_version) != int(user.token_version):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    request.state.claims = {
        "id": user.id,
        "role": user.role.value,
        "token_version": user.token_version,
    }

def create_token(user_id: int, role: Role, token_version: int, expires_in: int | None = None) -> str:
    if expires_in is not None:
        expires_in = int(expires_in)
    else:
        expires_in = int(settings.DEFAULT_EXP_MINUTES)
    return jwt.encode({
        "id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "role": role.value,
        "token_version": token_version,
    }, settings.JWT_SECRET_KEY, algorithm="HS256")

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

async def reset_password(session: AsyncSession, user_id: int, new_password: str) -> None:
    validate_password_strength(new_password)
    pwhash = PasswordHash.recommended()
    password_hash = await asyncio.to_thread(pwhash.hash, new_password)
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password = password_hash
    user.token_version += 1
    await session.commit()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _password_reset_token_key(token: str) -> str:
    return f"{PASSWORD_RESET_TOKEN_PREFIX}:{_token_digest(token)}"


async def check_password_reset_rate_limit(token: str) -> None:
    if not settings.REDIS_URL:
        return
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        key = f"{PASSWORD_RESET_ATTEMPT_PREFIX}:{_token_digest(token)}"
        attempts = await client.incr(key)
        if attempts == 1:
            await client.expire(key, 300)
        if attempts > 5:
            raise HTTPException(status_code=429, detail="Too many password reset attempts")
    finally:
        await client.aclose()

async def create_password_reset_token(user_id: int, ttl_seconds: int | None = None) -> str:
    if not settings.REDIS_URL:
        raise HTTPException(status_code=500, detail="Password reset token storage is not configured")

    token = secrets.token_urlsafe(32)
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

async def create_user(session: AsyncSession, username: str, email: str, password: str, role: Role = Role.USER) -> UserPublic:
    validate_password_strength(password)
    pwhash = PasswordHash.recommended()
    password_hash = await asyncio.to_thread(pwhash.hash, password)
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
