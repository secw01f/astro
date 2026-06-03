import os
import hashlib
import hmac
import time

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from src.web import web_router
from src.reporting import reporting_router
from src.recon import recon_router
from src.appsec import appsec_router
from src.asm import asm_router
from src.dns import dns_router
from src.threatmodel import threatmodel_router
from lib.tool import loader

load_dotenv()

api = FastAPI()
SECRET_KEY = os.getenv("SECRET_KEY", "")
PROTECTED_PREFIXES = ("/web", "/reporting", "/recon", "/appsec", "/asm", "/dns", "/threatmodel")
MAX_SKEW_SECONDS = 300


def _verify_signature(request: Request) -> bool:
    timestamp = request.headers.get("X-Astro-Timestamp")
    signature = request.headers.get("X-Astro-Signature")

    if not timestamp or not signature or not SECRET_KEY:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts) > MAX_SKEW_SECONDS:
        return False

    message = f"{timestamp}:{request.method.upper()}:{request.url.path}".encode("utf-8")
    expected = hmac.new(
        SECRET_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


@api.middleware("http")
async def verify_shared_secret(request: Request, call_next):
    if request.url.path.startswith(PROTECTED_PREFIXES):
        if not _verify_signature(request):
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

@api.on_event("startup")
async def startup():
    loader()

api.include_router(web_router)
api.include_router(reporting_router)
api.include_router(recon_router)
api.include_router(appsec_router)
api.include_router(asm_router)
api.include_router(dns_router)
api.include_router(threatmodel_router)