import logging
import json
import sys

from fastapi import FastAPI
from sqlmodel import select
import redis.asyncio as redis

from src.logging.config import log_config
from settings import settings
from lib.auth.auth import create_user, generate_password
from lib.auth.enums import Role
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

    if settings.SECRET_KEY == "supersecretkey" or settings.SECRET_KEY == "" or settings.SECRET_KEY is None or len(settings.SECRET_KEY) < 64:
        logger.error("SECRET_KEY is not set or insecure")
        raise SystemExit("SECRET_KEY is not set or insecure")

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
            await create_user(session, "stack", "stack@stack.local", password, Role.ADMIN)
            with open("/api/stack_user.json", "w") as f:
                json.dump({
                    "username": "stack",
                    "email": "stack@stack.local",
                    "password": password,
                }, f)
            logger.info(f"Stack user created and saved to /api/stack_user.json")
            client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                await client.set(f"auth:default_stack_user_active", "1")
                logger.info(f"Default stack user active set in Redis")
                await client.aclose()
            except Exception as e:
                logger.error(f"Failed to set default stack user active in Redis: {e}")
                await client.aclose()
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

        _dns_toolset_statement = select(ToolSet).where(
            ToolSet.name == "DNS",
            ToolSet.url == f"{settings.DEFAULT_TOOLS_BASE_URL}/dns",
            ToolSet.type == ToolType.HTTP,
        )
        dns_toolset = (await session.exec(_dns_toolset_statement)).first()
        
        if dns_toolset is None:
            logger.info("Creating default DNS toolset")
            dns_toolset = ToolSet(
                name="DNS",
                description="A toolset for DNS",
                url=f"{settings.DEFAULT_TOOLS_BASE_URL}/dns",
                type=ToolType.HTTP,
            )
            session.add(dns_toolset)
            await session.commit()
            await session.refresh(dns_toolset)
        else:
            logger.info("Default DNS toolset already exists")

        _tools = await get_tools(dns_toolset.url)
        _parsed_tools = ToolsResponse.model_validate(_tools)
        _existing_tools_statement = select(Tool).where(Tool.toolset_id == dns_toolset.id)
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
                    toolset_id=dns_toolset.id,
                    type=ToolType.HTTP,
                    url=dns_toolset.url,
                )
            )
            created_count += 1

        if created_count > 0:
            await session.commit()
            logger.info("Added %s new tool(s) to default DNS toolset", created_count)
        else:
            logger.info("Default DNS toolset tools already up to date")

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

        _asm_toolset_statement = select(ToolSet).where(
            ToolSet.name == "ASM",
            ToolSet.url == f"{settings.DEFAULT_TOOLS_BASE_URL}/asm",
            ToolSet.type == ToolType.HTTP,
        )
        asm_toolset = (await session.exec(_asm_toolset_statement)).first()

        if asm_toolset is None:
            logger.info("Creating default ASM toolset")
            asm_toolset = ToolSet(
                name="ASM",
                description="A toolset for Attack Surface Management",
                url=f"{settings.DEFAULT_TOOLS_BASE_URL}/asm",
                type=ToolType.HTTP,
            )
            session.add(asm_toolset)
            await session.commit()
            await session.refresh(asm_toolset)
        else:
            logger.info("Default ASM toolset already exists")

        _tools = await get_tools(asm_toolset.url)
        _parsed_tools = ToolsResponse.model_validate(_tools)
        _existing_tools_statement = select(Tool).where(Tool.toolset_id == asm_toolset.id)
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
                    toolset_id=asm_toolset.id,
                    type=ToolType.HTTP,
                    url=asm_toolset.url,
                )
            )
            created_count += 1

        if created_count > 0:
            await session.commit()
            logger.info("Added %s new tool(s) to default ASM toolset", created_count)
        else:
            logger.info("Default ASM toolset tools already up to date")

        _threatmodel_toolset_statement = select(ToolSet).where(
            ToolSet.name == "Threat Model",
            ToolSet.url == f"{settings.DEFAULT_TOOLS_BASE_URL}/threatmodel",
            ToolSet.type == ToolType.HTTP,
        )
        threatmodel_toolset = (await session.exec(_threatmodel_toolset_statement)).first()

        if threatmodel_toolset is None:
            logger.info("Creating default Threat Model toolset")
            threatmodel_toolset = ToolSet(
                name="Threat Model",
                description="A toolset for threat modeling",
                url=f"{settings.DEFAULT_TOOLS_BASE_URL}/threatmodel",
                type=ToolType.HTTP,
            )
            session.add(threatmodel_toolset)
            await session.commit()
            await session.refresh(threatmodel_toolset)
        else:
            logger.info("Default Threat Model toolset already exists")

        _tools = await get_tools(threatmodel_toolset.url)
        _parsed_tools = ToolsResponse.model_validate(_tools)
        _existing_tools_statement = select(Tool).where(Tool.toolset_id == threatmodel_toolset.id)
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
                    toolset_id=threatmodel_toolset.id,
                    type=ToolType.HTTP,
                    url=threatmodel_toolset.url,
                )
            )
            created_count += 1

        if created_count > 0:
            await session.commit()
            logger.info("Added %s new tool(s) to default Threat Model toolset", created_count)
        else:
            logger.info("Default Threat Model toolset tools already up to date")

        _github_repos_read_only_toolset_statement = select(ToolSet).where(
            ToolSet.name == "GitHub - Repos Read Only",
            ToolSet.url == "https://api.githubcopilot.com/mcp/x/repos/readonly",
            ToolSet.type == ToolType.MCP,
        )
        github_repos_read_only_toolset = (await session.exec(_github_repos_read_only_toolset_statement)).first()

        if github_repos_read_only_toolset is None:
            logger.info("Creating default GitHub - Repos Read Only toolset")
            github_repos_read_only_toolset = ToolSet(
                name="GitHub - Repos Read Only",
                description="A toolset for read only access to GitHub repositories",
                url="https://api.githubcopilot.com/mcp/x/repos/readonly",
                type=ToolType.MCP,
                auth_required=True,
            )
            session.add(github_repos_read_only_toolset)
            await session.commit()
            await session.refresh(github_repos_read_only_toolset)
            logger.info("Default GitHub - Repos Read Only toolset created")
        else:
            logger.info("Default GitHub - Repos Read Only toolset already exists")

        _github_repos_full_access_toolset_statement = select(ToolSet).where(
            ToolSet.name == "GitHub - Repos Full Access",
            ToolSet.url == "https://api.githubcopilot.com/mcp/x/repos",
            ToolSet.type == ToolType.MCP,
        )
        github_repos_full_access_toolset = (
            await session.exec(_github_repos_full_access_toolset_statement)
        ).first()

        if github_repos_full_access_toolset is None:
            logger.info("Creating default GitHub - Repos Full Access toolset")
            github_repos_full_access_toolset = ToolSet(
                name="GitHub - Repos Full Access",
                description="A toolset for full access to GitHub repositories",
                url="https://api.githubcopilot.com/mcp/x/repos",
                type=ToolType.MCP,
                auth_required=True,
            )
            session.add(github_repos_full_access_toolset)
            await session.commit()
            await session.refresh(github_repos_full_access_toolset)
            logger.info("Default GitHub - Repos Full Access toolset created")
        else:
            logger.info("Default GitHub - Repos Full Access toolset already exists")

        _github_git_read_only_toolset_statement = select(ToolSet).where(
            ToolSet.name == "GitHub - Git Read Only",
            ToolSet.url == "https://api.githubcopilot.com/mcp/x/git/readonly",
            ToolSet.type == ToolType.MCP,
        )
        github_git_read_only_toolset = (
            await session.exec(_github_git_read_only_toolset_statement)
        ).first()

        if github_git_read_only_toolset is None:
            logger.info("Creating default GitHub - Git Read Only toolset")
            github_git_read_only_toolset = ToolSet(
                name="GitHub - Git Read Only",
                description="A toolset for read only access to GitHub Git repositories",
                url="https://api.githubcopilot.com/mcp/x/git/readonly",
                type=ToolType.MCP,
                auth_required=True,
            )
            session.add(github_git_read_only_toolset)
            await session.commit()
            await session.refresh(github_git_read_only_toolset)
            logger.info("Default GitHub - Git Read Only toolset created")
        else:
            logger.info("Default GitHub - Git Read Only toolset already exists")

        _github_git_full_access_toolset_statement = select(ToolSet).where(
            ToolSet.name == "GitHub - Git Full Access",
            ToolSet.url == "https://api.githubcopilot.com/mcp/x/git",
            ToolSet.type == ToolType.MCP,
        )
        github_git_full_access_toolset = (
            await session.exec(_github_git_full_access_toolset_statement)
        ).first()

        if github_git_full_access_toolset is None:
            logger.info("Creating default GitHub - Git Full Access toolset")
            github_git_full_access_toolset = ToolSet(
                name="GitHub - Git Full Access",
                description="A toolset for full access to GitHub Git repositories",
                url="https://api.githubcopilot.com/mcp/x/git",
                type=ToolType.MCP,
                auth_required=True,
            )
            session.add(github_git_full_access_toolset)
            await session.commit()
            await session.refresh(github_git_full_access_toolset)
            logger.info("Default GitHub - Git Full Access toolset created")
        else:
            logger.info("Default GitHub - Git Full Access toolset already exists")

        _github_full_access_toolset_statement = select(ToolSet).where(
            ToolSet.name == "GitHub Full Access",
            ToolSet.url == "https://api.githubcopilot.com/mcp/",
            ToolSet.type == ToolType.MCP,
        )
        github_full_access_toolset = (
            await session.exec(_github_full_access_toolset_statement)
        ).first()

        if github_full_access_toolset is None:
            logger.info("Creating default GitHub Full Access toolset")
            github_full_access_toolset = ToolSet(
                name="GitHub Full Access",
                description="A toolset for full access to GitHub",
                url="https://api.githubcopilot.com/mcp/",
                type=ToolType.MCP,
                auth_required=True,
            )
            session.add(github_full_access_toolset)
            await session.commit()
            await session.refresh(github_full_access_toolset)
            logger.info("Default GitHub Full Access toolset created")
        else:
            logger.info("Default GitHub Full Access toolset already exists")

        logger.info(
            "Default toolsets ready - Users must configure per-user credentials via PUT /tool/toolset/{id}/credential for authenticated toolsets"
        )

    logger.info("Startup Complete")

api.include_router(auth_router)
api.include_router(agent_router)
api.include_router(stack_router)
api.include_router(tool_router)
api.include_router(llm_router)
api.include_router(message_router)