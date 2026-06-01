from sqlmodel import Field, SQLModel, Relationship, Column, Text, Index
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, model_validator
from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB

from lib.llm.enums import Provider
from lib.agent.enums import AgentRole, AgentType
from lib.tool.enums import ToolType, AuthType
from lib.auth.enums import Role

_AGENT_ROLE_PG = SAEnum(
    AgentRole,
    name="agentrole",
    values_callable=lambda cls: [m.value for m in cls],
)
_AGENT_TYPE_PG = SAEnum(
    AgentType,
    name="agenttype",
    values_callable=lambda cls: [m.value for m in cls],
)

# User Models
class UserBase(SQLModel):
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True)

class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    password: str
    role: Role = Field(default=Role.USER)
    enabled: bool | None= Field(default=True)
    created: datetime = Field(default_factory=datetime.utcnow)
    agents: List["Agent"] | None = Relationship(back_populates="user")
    stacks: List["Stack"] | None = Relationship(back_populates="user")
    credentials: List["Credential"] = Relationship(back_populates="user")
    memories: List["Memory"] = Relationship(back_populates="user")
    llms: List["LLM"] = Relationship(back_populates="user")
    toolsets: List["ToolSet"] = Relationship(back_populates="user")

class UserPublic(UserBase):
    id: int
    username: str
    email: str
    role: Role
    enabled: bool
    created: datetime

# LLM Models
class LLMBase(SQLModel):
    name: str
    provider: Provider

class LLM(LLMBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    credential_id: Optional[int] | None = Field(default=None, foreign_key="credential.id")
    key_id : Optional[str] | None = Field(default=None, unique=True)
    max_tokens: int | None = Field(default=None)
    region: Optional[str] | None = Field(default=None)
    model: str | None = Field(default=None)
    user_id: Optional[int] | None = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="llms")
    agents: List["Agent"] = Relationship(back_populates="llm")
    created: datetime = Field(default_factory=datetime.utcnow)

class LLMPublic(LLMBase):
    id: int
    name: str
    provider: Provider
    created: datetime

# Memory Models
class MemoryBase(SQLModel):
    content: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] = Field(sa_column=Column(Vector(384), nullable=False))
    category: str | None = Field(default=None)

class Memory(MemoryBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: Optional[int] | None = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="memories") 
    created: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index(
            "ix_memories_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

# Prompt Models
class PromptBase(SQLModel):
    prompt: str

class Prompt(PromptBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    role: AgentRole = Field(sa_column=Column(_AGENT_ROLE_PG, unique=True))
    agent_type: AgentType = Field(sa_column=Column(_AGENT_TYPE_PG))
    created: datetime = Field(default_factory=datetime.utcnow)

# Agent Models
class AgentBase(SQLModel):
    name: str
    description: str
    agent_type: AgentType
    role: AgentRole

class AgentStackLink(SQLModel, table=True):
    __tablename__ = "agent_stack_link"
    agent_id: int | None = Field(default=None, foreign_key="agent.id", primary_key=True)
    stack_id: int | None = Field(default=None, foreign_key="stack.id", primary_key=True)

class AgentToolSetLink(SQLModel, table=True):
    __tablename__ = "agent_toolset_link"
    agent_id: int = Field(foreign_key="agent.id", primary_key=True)
    toolset_id: int = Field(foreign_key="toolset.id", primary_key=True)

class AgentToolLink(SQLModel, table=True):
    __tablename__ = "agent_tool_link"
    agent_id: int = Field(foreign_key="agent.id", primary_key=True)
    tool_id: int = Field(foreign_key="tool.id", primary_key=True)

class Agent(AgentBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    agent_type: AgentType = Field(sa_column=Column(_AGENT_TYPE_PG))
    role: AgentRole = Field(sa_column=Column(_AGENT_ROLE_PG))
    user_id: Optional[int] | None = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="agents")
    stacks: List["Stack"] = Relationship(back_populates="agents", link_model=AgentStackLink)
    toolsets: List["ToolSet"] = Relationship(back_populates="agents", link_model=AgentToolSetLink)
    tools: List["Tool"] = Relationship(link_model=AgentToolLink)
    llm_id: int | None = Field(default=None, foreign_key="llm.id")
    llm: Optional["LLM"] = Relationship(back_populates="agents")
    system_prompt: str
    created: datetime = Field(default_factory=datetime.utcnow)

class AgentPublic(AgentBase):
    id: int
    name: str
    system_prompt: str
    stacks: List["StackSummaryPublic"]
    agent_type: AgentType
    role: AgentRole
    toolsets: List["ToolSetPublic"]
    tools: List["ToolPublic"] = []
    llm: Optional["LLMPublic"] = None
    created: datetime

    @model_validator(mode="before")
    @classmethod
    def _agent_orm_to_public(cls, data: Any) -> Any:
        if not isinstance(data, Agent):
            return data
        stacks = [StackSummaryPublic.model_validate(s) for s in (data.stacks or [])]
        toolsets = [ToolSetPublic.model_validate(t) for t in (data.toolsets or [])]
        tools = [ToolPublic.model_validate(t) for t in (data.tools or [])]
        llm_public = None
        llm_row = getattr(data, "llm", None)
        if llm_row is not None:
            llm_public = LLMPublic.model_validate(llm_row)
        return {
            "id": data.id,
            "name": data.name,
            "description": data.description,
            "agent_type": data.agent_type,
            "role": data.role,
            "system_prompt": data.system_prompt,
            "stacks": stacks,
            "toolsets": toolsets,
            "tools": tools,
            "llm": llm_public,
            "created": data.created,
        }

# Stack Models
class StackBase(SQLModel):
    name: str
    description: str

class Stack(StackBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: Optional[int]| None = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="stacks")
    agents: List["Agent"] = Relationship(back_populates="stacks", link_model=AgentStackLink)
    messages: List["Message"] = Relationship(back_populates="stack")
    last_position: int = Field(default=-1)
    created: datetime = Field(default_factory=datetime.utcnow)

class StackPublic(StackBase):
    id: int
    name: str
    description: str
    agents: List["AgentPublic"]
    created: datetime

class StackSummaryPublic(StackBase):
    id: int
    name: str
    description: str
    created: datetime

    @model_validator(mode="before")
    @classmethod
    def _stack_orm_to_summary(cls, data: Any) -> Any:
        if isinstance(data, Stack):
            return {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "created": data.created,
            }
        return data

# Tool Models
class ToolBase(SQLModel):
    name: str
    description: str

class Tool(ToolBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    input: Optional[dict] | None = Field(default=None, sa_column=Column(JSONB))
    type: ToolType
    toolset_id: Optional[int] = Field(default=None, foreign_key="toolset.id")
    toolset: Optional["ToolSet"] = Relationship(back_populates="tools")
    url: Optional[str] | None = Field(default=None)
    created: datetime = Field(default_factory=datetime.utcnow)

class ToolPublic(ToolBase):
    id: int
    name: str
    description: str
    type: ToolType
    input: Optional[dict] = None
    toolset_id: Optional[int] = None
    url: Optional[str] = None
    created: datetime

class ToolSetToolLink(SQLModel, table=True):
    __tablename__ = "toolset_tool_link"
    toolset_id: int = Field(foreign_key="toolset.id", primary_key=True)
    tool_id: int = Field(foreign_key="tool.id", primary_key=True)

class ToolSetBase(SQLModel):
    name: str
    description: str
    url: str = ""

class ToolSet(ToolSetBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tools: List["Tool"] = Relationship(back_populates="toolset")
    member_tools: List["Tool"] = Relationship(link_model=ToolSetToolLink)
    agents: List["Agent"] = Relationship(back_populates="toolsets", link_model=AgentToolSetLink)
    auth_required: bool = Field(default=False)
    auth_type: Optional[AuthType] | None = Field(default=AuthType.BEARER)
    header: Optional[str] | None = Field(default=None)
    user_id: Optional[int] | None = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="toolsets")
    type: ToolType
    created: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="before")
    def validate_auth_type(self, data: Any) -> Any:
        if self.auth_required and self.auth_type is None:
            raise ValueError("An authentication type is required for an authenticated toolset")
        return data

class UserToolSetCredential(SQLModel, table=True):
    __tablename__ = "user_toolset_credential"
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    toolset_id: int = Field(foreign_key="toolset.id", primary_key=True)
    credential_id: int = Field(foreign_key="credential.id")

class ToolSetPublic(ToolSetBase):
    id: int
    name: str
    description: str
    type: ToolType
    tools: List["ToolPublic"]
    scope: str
    user_id: Optional[int] = None
    auth_required: bool = False
    created: datetime

    @model_validator(mode="before")
    @classmethod
    def _toolset_orm_to_public(cls, data: Any) -> Any:
        if isinstance(data, ToolSet):
            if data.type == ToolType.LOGICAL:
                catalog_tools = data.member_tools or []
            else:
                catalog_tools = data.tools or []
            return {
                "id": data.id,
                "name": data.name,
                "description": data.description,
                "url": data.url or "",
                "type": data.type,
                "tools": [ToolPublic.model_validate(t) for t in catalog_tools],
                "scope": "shared" if data.user_id is None else "private",
                "user_id": data.user_id,
                "auth_required": data.auth_required,
                "created": data.created,
            }
        if isinstance(data, dict) and "scope" not in data:
            uid = data.get("user_id")
            data = {**data, "scope": "shared" if uid is None else "private"}
        return data

# Credential Models
class CredentialBase(SQLModel):
    token: str

class Credential(CredentialBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: Optional[int] | None = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="credentials")
    created: datetime = Field(default_factory=datetime.utcnow)

# Message Models
class MessageBase(SQLModel):
    role: str
    content: str = Field(sa_column=Column(Text, nullable=False))
    position: int

class Message(MessageBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    stack_id: int = Field(foreign_key="stack.id", index=True)
    stack: List["Stack"] = Relationship(back_populates="messages")
    created: datetime = Field(default_factory=datetime.utcnow)

class MessagePublic(MessageBase):
    id: int
    stack_id: int
    position: int
    content: str
    role: str
    created: datetime