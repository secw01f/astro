import jwt
import secrets
import string

from settings import settings
from src.db.models import User, UserPublic

from fastapi import HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from sqlmodel.ext.asyncio.session import AsyncSession
from pwdlib import PasswordHash
from datetime import datetime, timedelta, timezone

api_key_header = APIKeyHeader(name="X-API-KEY")

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

def create_token(user_id: int) -> str:
    return jwt.encode({
        "id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=int(settings.DEFAULT_EXP_MINUTES))
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

async def create_user(session: AsyncSession, username: str, email: str, password: str) -> UserPublic:
    pwhash = PasswordHash.recommended()
    password_hash = pwhash.hash(password)
    user = User(username=username, email=email, password=password_hash)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserPublic.model_validate(user)
