from pydantic import BaseModel, model_validator
from typing import Optional

from lib.llm.enums import Provider

class CreateLLM(BaseModel):
    name: str
    provider: Provider
    key: str
    key_id: Optional[str] | None = None
    max_tokens: Optional[int] | None = None
    model: str
    region: Optional[str] | None = None

    @model_validator(mode="after")
    def validate_keys(self):
        if self.provider == Provider.BEDROCK and self.key_id is None:
            raise ValueError("A Key ID is required for Bedrock")
        if self.provider == Provider.BEDROCK and self.key is None:
            raise ValueError("An Access Key is required for Bedrock")
        if self.provider == Provider.BEDROCK and self.region is None:
            raise ValueError("An AWS Region is required for Bedrock")
        if self.provider == Provider.OPENAI and self.key is None:
            raise ValueError("An OpenAI API Key is required for OpenAI")
        if self.provider == Provider.ANTHROPIC and self.key is None:
            raise ValueError("An Anthropic API Key is required for Anthropic")
        return self


class UpdateLLM(BaseModel):
    name: Optional[str] = None
    provider: Optional[Provider] = None
    key: Optional[str] = None
    key_id: Optional[str] = None
    max_tokens: Optional[int] = None
    model: Optional[str] = None
    region: Optional[str] = None

    @model_validator(mode="after")
    def validate_keys(self):
        fields_set = self.model_fields_set

        if "provider" not in fields_set:
            return self
        if self.provider == Provider.BEDROCK:
            if "key_id" not in fields_set:
                raise ValueError("A Key ID is required for Bedrock")
            if "key" not in fields_set:
                raise ValueError("An Access Key is required for Bedrock")
            if "region" not in fields_set:
                raise ValueError("An AWS Region is required for Bedrock")
        if self.provider == Provider.OPENAI:
            if "key" not in fields_set:
                raise ValueError("An OpenAI API Key is required for OpenAI")
        if self.provider == Provider.ANTHROPIC:
            if "key" not in fields_set:
                raise ValueError("An Anthropic API Key is required for Anthropic")

        return self