import logging

from fastapi import FastAPI
from sqlmodel import select

from src.logging.config import log_config
from settings import settings
from lib.auth.auth import create_user, generate_password
from src.db.db import init_db, async_session
from src.db.models import User, ToolSet, Tool, Prompt
from lib.agent.prompts import APPLICATION_SECURITY_SUPERVISOR_PROMPT, GOVERNANCE_RISK_COMPLIANCE_SUPERVISOR_PROMPT, DETECTION_INCIDENT_RESPONSE_SUPERVISOR_PROMPT, OFFENSIVE_SECURITY_SUPERVISOR_PROMPT, VULNERABILITY_MANAGEMENT_SUPERVISOR_PROMPT, APPLICATION_SECURITY_ARCHITECT_PROMPT, DETECTION_INCIDENT_RESPONSE_ARCHITECT_PROMPT, SECURITY_ENGINEERING_ARCHITECT_PROMPT, APPLICATION_SECURITY_ENGINEER_PROMPT, GOVERNANCE_RISK_COMPLIANCE_ENGINEER_PROMPT, DETECTION_INCIDENT_RESPONSE_ENGINEER_PROMPT, OFFENSIVE_SECURITY_ENGINEER_PROMPT, VULNERABILITY_MANAGEMENT_ENGINEER_PROMPT, APPLICATION_SECURITY_ANALYST_PROMPT, GOVERNANCE_RISK_COMPLIANCE_ANALYST_PROMPT, DETECTION_INCIDENT_RESPONSE_ANALYST_PROMPT, OFFENSIVE_SECURITY_ANALYST_PROMPT, VULNERABILITY_MANAGEMENT_ANALYST_PROMPT
from lib.agent.enums import AgentRole, AgentType
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

    logger.info("Initializing the database")
    await init_db()
    logger.info("Database initialized")
    
    async with async_session() as session:
        user = select(User).where(User.username == "stack")
        result = await session.exec(user)
        existing_user = result.first()
        
        if not existing_user:
            logger.info("Creating default \"stack\" User")
            password = generate_password(16)
            await create_user(session, "stack", "stack@stack.local", password)
            logger.info(f"Username: stack")
            logger.info(f"Password: {password}")
        else:
            logger.info(f"Default user already exists")

    logger.info("Populating prebuilt prompts")
    async with async_session() as session:
        _prompts_statement = select(Prompt)
        _prompts = (await session.exec(_prompts_statement)).all()
        if not _prompts:
            logger.info("Creating default prompts")
            _prompts = [Prompt(role=AgentRole.APPLICATION_SECURITY_SUPERVISOR, agent_type=AgentType.SUPERVISOR, prompt=APPLICATION_SECURITY_SUPERVISOR_PROMPT),
                        Prompt(role=AgentRole.GOVERNANCE_RISK_COMPLIANCE_SUPERVISOR, agent_type=AgentType.SUPERVISOR, prompt=GOVERNANCE_RISK_COMPLIANCE_SUPERVISOR_PROMPT),
                        Prompt(role=AgentRole.DETECTION_INCIDENT_RESPONSE_SUPERVISOR, agent_type=AgentType.SUPERVISOR, prompt=DETECTION_INCIDENT_RESPONSE_SUPERVISOR_PROMPT),
                        Prompt(role=AgentRole.OFFENSIVE_SECURITY_SUPERVISOR, agent_type=AgentType.SUPERVISOR, prompt=OFFENSIVE_SECURITY_SUPERVISOR_PROMPT),
                        Prompt(role=AgentRole.VULNERABILITY_MANAGEMENT_SUPERVISOR, agent_type=AgentType.SUPERVISOR, prompt=VULNERABILITY_MANAGEMENT_SUPERVISOR_PROMPT),
                        Prompt(role=AgentRole.APPLICATION_SECURITY_ARCHITECT, agent_type=AgentType.SUPPORTING, prompt=APPLICATION_SECURITY_ARCHITECT_PROMPT),
                        Prompt(role=AgentRole.DETECTION_INCIDENT_RESPONSE_ARCHITECT, agent_type=AgentType.SUPPORTING, prompt=DETECTION_INCIDENT_RESPONSE_ARCHITECT_PROMPT),
                        Prompt(role=AgentRole.SECURITY_ENGINEERING_ARCHITECT, agent_type=AgentType.SUPPORTING, prompt=SECURITY_ENGINEERING_ARCHITECT_PROMPT),
                        Prompt(role=AgentRole.APPLICATION_SECURITY_ENGINEER, agent_type=AgentType.SUPPORTING, prompt=APPLICATION_SECURITY_ENGINEER_PROMPT),
                        Prompt(role=AgentRole.GOVERNANCE_RISK_COMPLIANCE_ENGINEER, agent_type=AgentType.SUPPORTING, prompt=GOVERNANCE_RISK_COMPLIANCE_ENGINEER_PROMPT),
                        Prompt(role=AgentRole.DETECTION_INCIDENT_RESPONSE_ENGINEER, agent_type=AgentType.SUPPORTING, prompt=DETECTION_INCIDENT_RESPONSE_ENGINEER_PROMPT),
                        Prompt(role=AgentRole.OFFENSIVE_SECURITY_ENGINEER, agent_type=AgentType.SUPPORTING, prompt=OFFENSIVE_SECURITY_ENGINEER_PROMPT),
                        Prompt(role=AgentRole.VULNERABILITY_MANAGEMENT_ENGINEER, agent_type=AgentType.SUPPORTING, prompt=VULNERABILITY_MANAGEMENT_ENGINEER_PROMPT),
                        Prompt(role=AgentRole.APPLICATION_SECURITY_ANALYST, agent_type=AgentType.SUPPORTING, prompt=APPLICATION_SECURITY_ANALYST_PROMPT),
                        Prompt(role=AgentRole.GOVERNANCE_RISK_COMPLIANCE_ANALYST, agent_type=AgentType.SUPPORTING, prompt=GOVERNANCE_RISK_COMPLIANCE_ANALYST_PROMPT),
                        Prompt(role=AgentRole.DETECTION_INCIDENT_RESPONSE_ANALYST, agent_type=AgentType.SUPPORTING, prompt=DETECTION_INCIDENT_RESPONSE_ANALYST_PROMPT),
                        Prompt(role=AgentRole.OFFENSIVE_SECURITY_ANALYST, agent_type=AgentType.SUPPORTING, prompt=OFFENSIVE_SECURITY_ANALYST_PROMPT),
                        Prompt(role=AgentRole.VULNERABILITY_MANAGEMENT_ANALYST, agent_type=AgentType.SUPPORTING, prompt=VULNERABILITY_MANAGEMENT_ANALYST_PROMPT)]
            session.add_all(_prompts)
            await session.commit()

    logger.info("Prebuilt prompts populated")

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

        _recon_toolset_statement = select(ToolSet).where(
            ToolSet.name == "Recon",
            ToolSet.url == f"{settings.DEFAULT_TOOLS_BASE_URL}/recon",
            ToolSet.type == ToolType.HTTP,
        )
        recon_toolset = (await session.exec(_recon_toolset_statement)).first()

        if recon_toolset is None:
            logger.info("Creating default Recon toolset")
            recon_toolset = ToolSet(
                name="Recon",
                description="A toolset for reconnaissance",
                url=f"{settings.DEFAULT_TOOLS_BASE_URL}/recon",
                type=ToolType.HTTP,
            )
            session.add(recon_toolset)
            await session.commit()
            await session.refresh(recon_toolset)
        else:
            logger.info("Default Recon toolset already exists")

        _tools = await get_tools(recon_toolset.url)
        _parsed_tools = ToolsResponse.model_validate(_tools)
        _existing_tools_statement = select(Tool).where(Tool.toolset_id == recon_toolset.id)
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
                    toolset_id=recon_toolset.id,
                    type=ToolType.HTTP,
                    url=recon_toolset.url,
                )
            )
            created_count += 1

        if created_count > 0:
            await session.commit()
            logger.info("Added %s new tool(s) to default Recon toolset", created_count)
        else:
            logger.info("Default Recon toolset tools already up to date")

    _reporting_toolset_statement = select(ToolSet).where(
        ToolSet.name == "Reporting",
        ToolSet.url == f"{settings.DEFAULT_TOOLS_BASE_URL}/reporting",
        ToolSet.type == ToolType.HTTP,
    )
    reporting_toolset = (await session.exec(_reporting_toolset_statement)).first()

    if reporting_toolset is None:
        logger.info("Creating default Reporting toolset")
        reporting_toolset = ToolSet(
            name="Reporting",
            description="A toolset for reporting",
            url=f"{settings.DEFAULT_TOOLS_BASE_URL}/reporting",
            type=ToolType.HTTP,
        )
        session.add(reporting_toolset)
        await session.commit()
        await session.refresh(reporting_toolset)
    else:
        logger.info("Default Reporting toolset already exists")

    _tools = await get_tools(reporting_toolset.url)
    _parsed_tools = ToolsResponse.model_validate(_tools)
    _existing_tools_statement = select(Tool).where(Tool.toolset_id == reporting_toolset.id)
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
                toolset_id=reporting_toolset.id,
                type=ToolType.HTTP,
                url=reporting_toolset.url,
            )
        )
        created_count += 1

    if created_count > 0:
        await session.commit()
        logger.info("Added %s new tool(s) to default Reporting toolset", created_count)
    else:
        logger.info("Default Reporting toolset tools already up to date")

    logger.info("Default toolsets ready")

    logger.info("Startup Complete")

api.include_router(auth_router)
api.include_router(agent_router)
api.include_router(stack_router)
api.include_router(tool_router)
api.include_router(llm_router)
api.include_router(message_router)