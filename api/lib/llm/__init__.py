
from typing import Optional
from haystack.utils import Secret
from haystack_integrations.components.generators.anthropic import AnthropicChatGenerator
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack_integrations.components.generators.amazon_bedrock import AmazonBedrockChatGenerator

from lib.llm.enums import Provider

def chat_generator(provider: Provider, model: str, key: str, key_id: Optional[str] = None, region: Optional[str] = None, max_tokens: Optional[int] = None):
    generation_kwargs = {"max_tokens": max_tokens} if max_tokens is not None else {}

    if provider.value == "anthropic":
        return AnthropicChatGenerator(
            model=model,
            api_key=Secret.from_token(key),
            generation_kwargs=generation_kwargs,
        )
    
    if provider.value == "openai":
        return OpenAIChatGenerator(
            model=model,
            api_key=Secret.from_token(key),
            generation_kwargs=generation_kwargs,
        )

    if provider.value == "bedrock":
        return AmazonBedrockChatGenerator(
            model=model,
            aws_access_key_id=key_id,
            aws_secret_access_key=key,
            aws_region_name=region,
            generation_kwargs=generation_kwargs,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")