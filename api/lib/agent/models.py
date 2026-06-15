from typing import Optional, Self

from pydantic import BaseModel, model_validator

from lib.agent.enums import AgentType, AgentRole

_SUPERVISOR_ROLES = frozenset(
    {
        AgentRole.APPLICATION_SECURITY_SUPERVISOR,
        AgentRole.GOVERNANCE_RISK_COMPLIANCE_SUPERVISOR,
        AgentRole.DETECTION_INCIDENT_RESPONSE_SUPERVISOR,
        AgentRole.OFFENSIVE_SECURITY_SUPERVISOR,
        AgentRole.VULNERABILITY_MANAGEMENT_SUPERVISOR,
        AgentRole.CUSTOM_SUPERVISOR,
    }
)

_SUPPORTING_ROLES = frozenset(
    {
        AgentRole.APPLICATION_SECURITY_ARCHITECT,
        AgentRole.DETECTION_INCIDENT_RESPONSE_ARCHITECT,
        AgentRole.SECURITY_ENGINEERING_ARCHITECT,
        AgentRole.APPLICATION_SECURITY_ENGINEER,
        AgentRole.GOVERNANCE_RISK_COMPLIANCE_ENGINEER,
        AgentRole.DETECTION_INCIDENT_RESPONSE_ENGINEER,
        AgentRole.OFFENSIVE_SECURITY_ENGINEER,
        AgentRole.VULNERABILITY_MANAGEMENT_ENGINEER,
        AgentRole.APPLICATION_SECURITY_ANALYST,
        AgentRole.GOVERNANCE_RISK_COMPLIANCE_ANALYST,
        AgentRole.DETECTION_INCIDENT_RESPONSE_ANALYST,
        AgentRole.OFFENSIVE_SECURITY_ANALYST,
        AgentRole.VULNERABILITY_MANAGEMENT_ANALYST,
        AgentRole.CUSTOM_SUPPORTING_AGENT,
    }
)


def validate_agent_configuration(
    agent_type: AgentType,
    role: AgentRole,
    toolset_ids: list[int] | None = None,
    tool_ids: list[int] | None = None,
) -> None:
    if agent_type is AgentType.SUPERVISOR and role not in _SUPERVISOR_ROLES:
        allowed = ", ".join(sorted(r.name for r in _SUPERVISOR_ROLES))
        raise ValueError(f"Supervisor type requires role to be one of: {allowed}")
    if agent_type is AgentType.SUPPORTING and role not in _SUPPORTING_ROLES:
        allowed = ", ".join(sorted(r.name for r in _SUPPORTING_ROLES))
        raise ValueError(f"Supporting type requires role to be one of: {allowed}")
    if agent_type is AgentType.SUPERVISOR and toolset_ids:
        raise ValueError("Supervisor agents cannot have toolsets; attach toolsets to supporting agents instead.")
    if agent_type is AgentType.SUPERVISOR and tool_ids:
        raise ValueError("Supervisor agents cannot have tools; attach tools to supporting agents instead.")


class CreateAgent(BaseModel):
    name: str
    description: str
    system_prompt: Optional[str] = None
    llm: int
    type: AgentType
    role: AgentRole
    toolset_ids: Optional[list[int]] = None
    tool_ids: Optional[list[int]] = None

    @model_validator(mode="after")
    def validate_type_and_role(self) -> Self:
        validate_agent_configuration(self.type, self.role, self.toolset_ids, self.tool_ids)
        return self

class UpdateAgent(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    llm: Optional[int] = None
    type: Optional[AgentType] = None
    role: Optional[AgentRole] = None
    toolset_ids: Optional[list[int]] = None
    tool_ids: Optional[list[int]] = None

class UpdatePrompt(BaseModel):
    prompt: str
