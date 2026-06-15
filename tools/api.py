import os
import hashlib
import hmac
import time
import redis.asyncio as redis

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from src.web import web_router
from src.reporting import reporting_router
from src.asm import asm_router
from src.dns import dns_router
from src.threatmodel import threatmodel_router

load_dotenv()

_docs_enabled = os.getenv("ENV", "") == "dev"
api = FastAPI(
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
TOOLS_HMAC_SECRET = os.getenv("TOOLS_HMAC_SECRET", "")
REDIS_URL = os.getenv("REDIS_URL")
PROTECTED_PREFIXES = ("/web", "/reporting", "/asm", "/dns", "/threatmodel")
MAX_SKEW_SECONDS = 300
_LOCAL_NONCES: dict[str, int] = {}


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _remember_nonce(nonce: str, expires_at: int) -> bool:
    if REDIS_URL:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            inserted = await client.set(
                f"astro:hmac_nonce:{nonce}",
                "1",
                ex=MAX_SKEW_SECONDS,
                nx=True,
            )
            return bool(inserted)
        except Exception:
            return False
        finally:
            await client.aclose()

    now = int(time.time())
    for key, expiry in list(_LOCAL_NONCES.items()):
        if expiry <= now:
            _LOCAL_NONCES.pop(key, None)
    if nonce in _LOCAL_NONCES:
        return False
    _LOCAL_NONCES[nonce] = expires_at
    return True


async def _verify_signature(request: Request) -> bool:
    timestamp = request.headers.get("X-Astro-Timestamp")
    signature = request.headers.get("X-Astro-Signature")
    body_sha = request.headers.get("X-Astro-Body-SHA256")
    nonce = request.headers.get("X-Astro-Nonce")
    user_header = request.headers.get("X-Astro-User-Id", "")

    if not timestamp or not signature or not body_sha or not nonce or not TOOLS_HMAC_SECRET:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts) > MAX_SKEW_SECONDS:
        return False
    if not await _remember_nonce(nonce, now + MAX_SKEW_SECONDS):
        return False

    body = await request.body()
    expected_body_sha = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(body_sha, expected_body_sha):
        return False

    message = f"{timestamp}:{request.method.upper()}:{request.url.path}:{body_sha}:{user_header}:{nonce}".encode("utf-8")
    expected = hmac.new(
        TOOLS_HMAC_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@api.middleware("http")
async def verify_shared_secret(request: Request, call_next):
    if request.url.path.startswith(PROTECTED_PREFIXES):
        if not await _verify_signature(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing request signature"},
            )
        user_header = request.headers.get("X-Astro-User-Id")
        if user_header:
            try:
                user_id = int(user_header)
                if user_id > 0:
                    request.state.user_id = user_id
            except ValueError:
                pass
    return await call_next(request)

api.include_router(web_router)
api.include_router(reporting_router)
api.include_router(asm_router)
api.include_router(dns_router)
api.include_router(threatmodel_router)
