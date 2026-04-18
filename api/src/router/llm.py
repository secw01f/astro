import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlmodel import select

from src.db.db import session_dep
from src.db.models import Agent, LLM, LLMPublic
from lib.auth.auth import verify_token

from lib.llm.models import CreateLLM, UpdateLLM
from lib.llm import encrypt_llm_api_key

llm_router = APIRouter(prefix="/llm", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)

@llm_router.get("/llms")
async def get_all_llms(request: Request, session: session_dep) -> dict[str, list[LLMPublic]]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = select(LLM).where(LLM.user_id == user_id)
    results = await session.exec(statement)
    llms = results.all()

    return {"llms": [LLMPublic.model_validate(llm) for llm in llms]}

@llm_router.get("/{id}")
async def get_llm_by_id(request: Request, id: int, session: session_dep) -> dict[str, LLMPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = select(LLM).where(LLM.id == id, LLM.user_id == user_id)
    result = await session.exec(statement)
    llm = result.first()

    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")
    return {"llm": LLMPublic.model_validate(llm)}

@llm_router.post("/new")
async def new_llm(request: Request, llm: CreateLLM, session: session_dep) -> dict[str, LLMPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    new_llm = LLM(**{k: v for k, v in llm.model_dump().items()})
    new_llm.key = encrypt_llm_api_key(llm.key)
    new_llm.user_id = user_id
    session.add(new_llm)
    await session.commit()
    await session.refresh(new_llm)
    return {"llm": LLMPublic.model_validate(new_llm)}

@llm_router.patch("/{id}")
async def update_llm(request: Request, id: int, session: session_dep, body: Annotated[UpdateLLM, Body(...)]) -> dict[str, LLMPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = select(LLM).where(LLM.id == id, LLM.user_id == user_id)
    result = await session.exec(statement)
    existing_llm = result.first()

    if not existing_llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    updates = body.model_dump(exclude_unset=True)
    key_plain = updates.pop("key", None)
    for key, value in updates.items():
        setattr(existing_llm, key, value)
    if key_plain is not None:
        existing_llm.key = encrypt_llm_api_key(key_plain)

    await session.commit()
    await session.refresh(existing_llm)
    return {"llm": LLMPublic.model_validate(existing_llm)}

@llm_router.delete("/{id}")
async def delete_llm(request: Request, id: int, session: session_dep) -> dict[str, str]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = select(LLM).where(LLM.id == id, LLM.user_id == user_id)
    result = await session.exec(statement)
    llm = result.first()

    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    agent_statement = select(Agent).where(Agent.user_id == user_id, Agent.llm_id == llm.id)
    agent_result = await session.exec(agent_statement)
    agents_using_llm = agent_result.all()
    for agent in agents_using_llm:
        agent.llm_id = None

    await session.delete(llm)
    await session.commit()
    return {"message": "LLM deleted successfully"}