
from typing import Optional
from haystack.utils import Secret
from haystack_integrations.components.generators.anthropic import AnthropicChatGenerator
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack_integrations.components.generators.amazon_bedrock import AmazonBedrockChatGenerator

from lib.llm.enums import Provider
from lib.llm.limiter import RateLimitedChatGenerator, RedisPromptCache, RedisTokenBucketLimiter
from settings import settings

_limiter = RedisTokenBucketLimiter()
_cache = RedisPromptCache()

def chat_generator(provider: Provider, model: str, key: str, key_id: Optional[str] = None, region: Optional[str] = None, max_tokens: Optional[int] = None):
    generation_kwargs = {"max_tokens": max_tokens} if max_tokens is not None else {}
    generator = None

    if provider.value == "anthropic":
        generator = AnthropicChatGenerator(
            model=model,
            api_key=Secret.from_token(key),
            generation_kwargs=generation_kwargs,
        )
    elif provider.value == "openai":
        generator = OpenAIChatGenerator(
            model=model,
            api_key=Secret.from_token(key),
            generation_kwargs=generation_kwargs,
        )
    elif provider.value == "bedrock":
        generator = AmazonBedrockChatGenerator(
            model=model,
            aws_access_key_id=key_id,
            aws_secret_access_key=key,
            aws_region_name=region,
            generation_kwargs=generation_kwargs,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    if settings.LLM_LIMITER_ENABLED or settings.LLM_PROMPT_CACHE_ENABLED:
        return RateLimitedChatGenerator(provider.value, model, generator, _limiter, cache=_cache)
    return generator