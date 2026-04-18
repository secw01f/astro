from fastapi import FastAPI
from src.web import web_router
from lib.tool import loader

api = FastAPI()

@api.on_event("startup")
async def startup():
    loader()

api.include_router(web_router)