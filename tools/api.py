from fastapi import FastAPI
from src.web import web_router
from src.reporting import reporting_router
from src.recon import recon_router
from src.appsec import appsec_router
from lib.tool import loader

api = FastAPI()

@api.on_event("startup")
async def startup():
    loader()

api.include_router(web_router)
api.include_router(reporting_router)
api.include_router(recon_router)
api.include_router(appsec_router)