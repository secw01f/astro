import logging
import json
import redis.asyncio as redis

from fastapi import FastAPI
from sqlmodel import select

from src.logging.config import log_config
from settings import settings
from lib.auth.auth import create_user, generate_password
from lib.auth.enums import Role
from src.db.db import init_db, async_session
from src.db.models import Credential, LLM, User, UserToolSetCredential, ToolSet, Tool, Prompt
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
from src.tool.memory import warm_memory_model

log_config()

api = FastAPI(
    docs_url="/docs" if settings.ENV == "dev" else None,
    redoc_url="/redoc" if settings.ENV == "dev" else None,
    openapi_url="/openapi.json" if settings.ENV == "dev" else None,
)
logger = logging.getLogger(__name__)


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _invalidate_legacy_credentials(session) -> None:
    statement = select(Credential).where(
        Credential.crypto_version != settings.CREDENTIAL_CRYPTO_VERSION
    )
    legacy_credentials = (await session.exec(statement)).all()
    credential_ids = [
        credential.id for credential in legacy_credentials if credential.id is not None
    ]
    if not credential_ids:
        return

    llms = (
        await session.exec(select(LLM).where(LLM.credential_id.in_(credential_ids)))
    ).all()
    for llm in llms:
        llm.credential_id = None

    links = (
        await session.exec(
            select(UserToolSetCredential).where(
                UserToolSetCredential.credential_id.in_(credential_ids)
            )
        )
    ).all()
    for link in links:
        await session.delete(link)

    for credential in legacy_credentials:
        await session.delete(credential)

    await session.commit()
    logger.warning(
        "Invalidated %s credential(s) created with an obsolete credential encryption format",
        len(credential_ids),
    )


async def _sync_default_http_toolset(session, name: str, description: str, path: str) -> None:
    url = f"{settings.DEFAULT_TOOLS_BASE_URL}/{path}"
    statement = select(ToolSet).where(
        ToolSet.name == name,
        ToolSet.url == url,
        ToolSet.type == ToolType.HTTP,
    )
    toolset = (await session.exec(statement)).first()

    if toolset is None:
        logger.info("Creating default %s toolset", name)
        toolset = ToolSet(
            name=name,
            description=description,
            url=url,
            type=ToolType.HTTP,
        )
        session.add(toolset)
        await session.commit()
        await session.refresh(toolset)
    else:
        logger.info("Default %s toolset already exists", name)

    try:
        tools = await get_tools(toolset.url)
        parsed_tools = ToolsResponse.model_validate(tools)
    except Exception as exc:
        logger.warning("Could not sync default %s toolset tools: %s", name, exc)
        return

    existing_tools_statement = select(Tool).where(Tool.toolset_id == toolset.id)
    existing_tools = (await session.exec(existing_tools_statement)).all()
    existing_tool_names = {tool.name for tool in existing_tools}
    created_count = 0

    for tool in parsed_tools.tools:
        if tool.name in existing_tool_names:
            continue
        session.add(
            Tool(
                name=tool.name,
                description=tool.description,
                input=tool.input_schema,
                toolset_id=toolset.id,
                type=ToolType.HTTP,
                url=toolset.url,
            )
        )
        created_count += 1

    if created_count > 0:
        await session.commit()
        logger.info("Added %s new tool(s) to default %s toolset", created_count, name)
    else:
        logger.info("Default %s toolset tools already up to date", name)

@api.on_event("startup")
async def startup_event():
    logger.info("API startup initiated")

    logger.info("Initializing the database")
    await init_db()
    logger.info("Database initialized")

    async with async_session() as session:
        await _invalidate_legacy_credentials(session)

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

    try:
        await warm_memory_model()
        logger.info("Memory embedding model warmed")
    except Exception as exc:
        logger.warning("Could not warm memory embedding model: %s", exc)

    logger.info("Initializing default toolsets")
    async with async_session() as session:
        for name, description, path in (
            ("Web", "A toolset for browsing the web", "web"),
            ("DNS", "A toolset for DNS", "dns"),
            ("Reporting", "A toolset for reporting", "reporting"),
            ("ASM", "A toolset for Attack Surface Management", "asm"),
            ("Threat Model", "A toolset for threat modeling", "threatmodel"),
        ):
            await _sync_default_http_toolset(session, name, description, path)

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
