import logging

from fastapi import FastAPI
from sqlmodel import select

from src.logging.config import log_config
from settings import settings
from lib.auth.auth import create_user, generate_password
from src.db.db import init_db, async_session
from src.db.models import User, ToolSet, Tool
from lib.tool.http import get_tools
from lib.tool.models import ToolsResponse
from lib.tool.enums import ToolType
from src.router.auth import auth_router
from src.router.agent import agent_router
from src.router.stack import stack_router
from src.router.tool import tool_router
from src.router.llm import llm_router
from src.router.message import message_router

log_config()

api = FastAPI()
logger = logging.getLogger(__name__)

@api.on_event("startup")
async def startup_event():
    logger.info("API startup initiated")

    logger.info("Initializing Database")
    await init_db()
    logger.info("Database Initialized")
    
    async with async_session() as session:
        user = select(User).where(User.username == "stack")
        result = await session.exec(user)
        existing_user = result.first()
        
        if not existing_user:
            logger.info("Creating Default \"stack\" User")
            password = generate_password(16)
            await create_user(session, "stack", "stack@stack.local", password)
            logger.info(f"Username: stack")
            logger.info(f"Password: {password}")
        else:
            logger.info(f"Default user already exists")

    logger.info("Initializing default toolsets")
    async with async_session() as session:
        _web_toolset_statement = select(ToolSet).where(
            ToolSet.name == "Web",
            ToolSet.url == f"{settings.DEFAULT_TOOLS_BASE_URL}/web",
            ToolSet.type == ToolType.HTTP,
        )
        web_toolset = (await session.exec(_web_toolset_statement)).first()

        if web_toolset is None:
            logger.info("Creating default Web toolset")
            web_toolset = ToolSet(
                name="Web",
                description="A toolset for browsing the web",
                url=f"{settings.DEFAULT_TOOLS_BASE_URL}/web",
                type=ToolType.HTTP,
            )
            session.add(web_toolset)
            await session.commit()
            await session.refresh(web_toolset)
        else:
            logger.info("Default Web toolset already exists")

        _tools = await get_tools(web_toolset.url)
        _parsed_tools = ToolsResponse.model_validate(_tools)
        _existing_tools_statement = select(Tool).where(Tool.toolset_id == web_toolset.id)
        _existing_tools = (await session.exec(_existing_tools_statement)).all()
        _existing_tool_names = {tool.name for tool in _existing_tools}
        created_count = 0
    
        for tool in _parsed_tools.tools:
            if tool.name in _existing_tool_names:
                continue
            session.add(
                Tool(
                    name=tool.name,
                    description=tool.description,
                    input=tool.input_schema,
                    toolset_id=web_toolset.id,
                    type=ToolType.HTTP,
                    url=web_toolset.url,
                )
            )
            created_count += 1

        if created_count > 0:
            await session.commit()
            logger.info("Added %s new tool(s) to default Web toolset", created_count)
        else:
            logger.info("Default Web toolset tools already up to date")

    logger.info("Default toolsets ready")

    logger.info("Startup Complete")

api.include_router(auth_router)
api.include_router(agent_router)
api.include_router(stack_router)
api.include_router(tool_router)
api.include_router(llm_router)
api.include_router(message_router)