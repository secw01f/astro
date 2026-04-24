import asyncio
import hashlib
import json
import logging
import pickle
import time

from typing import Any
from redis.asyncio import Redis

from settings import settings

logger = logging.getLogger(__name__)

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local state = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(state[1])
local ts = tonumber(state[2])

if tokens == nil then
  tokens = capacity
end
if ts == nil then
  ts = now_ms
end

if now_ms > ts then
  local elapsed = now_ms - ts
  tokens = math.min(capacity, tokens + (elapsed * refill_per_ms))
  ts = now_ms
end

if tokens >= requested then
  tokens = tokens - requested
  redis.call("HMSET", key, "tokens", tokens, "ts", ts)
  redis.call("PEXPIRE", key, 120000)
  return {1, 0}
end

local deficit = requested - tokens
local wait_ms = math.ceil(deficit / refill_per_ms)
redis.call("HMSET", key, "tokens", tokens, "ts", ts)
redis.call("PEXPIRE", key, 120000)
return {0, wait_ms}
"""


def _estimate_message_tokens(messages: Any) -> int:
    if not messages:
        return 0
    text_parts: list[str] = []
    for message in messages:
        text = getattr(message, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            text_parts.append(content)
            continue
        text_parts.append(str(message))
    combined = "\n".join(text_parts)

    return max(1, len(combined) // 4)


def _estimate_requested_tokens(kwargs: dict[str, Any]) -> int:
    prompt_tokens = _estimate_message_tokens(kwargs.get("messages"))
    generation_kwargs = kwargs.get("generation_kwargs") or {}
    requested_output = generation_kwargs.get("max_tokens")
    if not isinstance(requested_output, int) or requested_output <= 0:
        requested_output = settings.LLM_LIMITER_DEFAULT_OUTPUT_TOKENS
    return max(1, prompt_tokens + requested_output)


def _normalize_for_cache(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _normalize_for_cache(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_for_cache(v) for v in value]
    if hasattr(value, "to_dict"):
        try:
            return _normalize_for_cache(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return _normalize_for_cache(value.model_dump())
        except Exception:
            pass
    return repr(value)


def _cache_key(provider: str, model: str, payload: dict[str, Any]) -> str:
    normalized = {
        "provider": provider,
        "model": model,
        "payload": _normalize_for_cache(payload),
    }
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"llm:prompt-cache:{digest}"


class RedisTokenBucketLimiter:
    def __init__(self) -> None:
        self._redis: Redis | None = None
        self._script_sha: str | None = None
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> Redis | None:
        if not settings.LLM_LIMITER_ENABLED:
            return None
        if not settings.REDIS_URL:
            logger.warning("LLM limiter enabled but REDIS_URL is not set; limiter is bypassed")
            return None
        if self._redis is not None:
            return self._redis
        async with self._lock:
            if self._redis is None:
                self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            return self._redis

    async def _eval_bucket(self, key: str, requested_tokens: int) -> tuple[bool, int]:
        redis = await self._get_redis()
        if redis is None:
            return True, 0

        capacity = float(settings.LLM_TOKEN_LIMIT_PER_MINUTE)
        refill_per_ms = capacity / 60000.0
        now_ms = int(time.time() * 1000)
        args = [capacity, refill_per_ms, now_ms, float(requested_tokens)]

        try:
            if self._script_sha is None:
                self._script_sha = await redis.script_load(_TOKEN_BUCKET_LUA)
            result = await redis.evalsha(self._script_sha, 1, key, *args)
        except Exception:
            # Reload once in case Redis script cache was flushed.
            self._script_sha = await redis.script_load(_TOKEN_BUCKET_LUA)
            result = await redis.evalsha(self._script_sha, 1, key, *args)

        allowed = int(result[0]) == 1
        wait_ms = int(result[1])
        return allowed, wait_ms

    async def acquire(self, provider: str, model: str, payload: dict[str, Any]) -> None:
        if not settings.LLM_LIMITER_ENABLED:
            return
        requested_tokens = _estimate_requested_tokens(payload)
        capacity = max(1, int(settings.LLM_TOKEN_LIMIT_PER_MINUTE))
        if requested_tokens > capacity:

            logger.warning(
                "Requested token reservation (%s) exceeded bucket capacity (%s); clamping to capacity",
                requested_tokens,
                capacity,
            )
            requested_tokens = capacity
        scope = json.dumps({"provider": provider, "model": model}, sort_keys=True)
        scope_hash = hashlib.sha1(scope.encode("utf-8")).hexdigest()
        key = f"llm:bucket:{scope_hash}"

        while True:
            allowed, wait_ms = await self._eval_bucket(key, requested_tokens)
            if allowed:
                return
            sleep_ms = max(wait_ms, settings.LLM_LIMITER_POLL_INTERVAL_MS)
            await asyncio.sleep(sleep_ms / 1000.0)


class RedisPromptCache:
    def __init__(self) -> None:
        self._redis: Redis | None = None
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> Redis | None:
        if not settings.LLM_PROMPT_CACHE_ENABLED:
            return None
        if not settings.REDIS_URL:
            logger.warning("LLM prompt cache enabled but REDIS_URL is not set; cache is bypassed")
            return None
        if self._redis is not None:
            return self._redis
        async with self._lock:
            if self._redis is None:
                self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=False)
            return self._redis

    async def get(self, provider: str, model: str, payload: dict[str, Any]) -> Any | None:
        redis = await self._get_redis()
        if redis is None:
            return None
        key = _cache_key(provider, model, payload)
        blob = await redis.get(key)
        if not blob:
            return None
        try:
            return pickle.loads(blob)
        except Exception:
            logger.warning("Failed to deserialize cached LLM response; evicting key")
            await redis.delete(key)
            return None

    async def set(self, provider: str, model: str, payload: dict[str, Any], response: Any) -> None:
        redis = await self._get_redis()
        if redis is None:
            return
        key = _cache_key(provider, model, payload)
        blob = pickle.dumps(response)
        await redis.set(key, blob, ex=settings.LLM_PROMPT_CACHE_TTL_SECONDS)


class RateLimitedChatGenerator:
    def __init__(
        self,
        provider: str,
        model: str,
        generator: Any,
        limiter: RedisTokenBucketLimiter,
        cache: RedisPromptCache | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._generator = generator
        self._limiter = limiter
        self._cache = cache

    async def _cached_get(self, payload: dict[str, Any]) -> Any | None:
        if self._cache is None:
            return None
        return await self._cache.get(self._provider, self._model, payload)

    async def _cached_set(self, payload: dict[str, Any], response: Any) -> None:
        if self._cache is None:
            return
        await self._cache.set(self._provider, self._model, payload, response)

    async def run_async(self, messages, tools=None, **kwargs):
        payload = dict(kwargs)
        payload["messages"] = messages
        payload["tools"] = tools
        use_cache = not tools
        if use_cache:
            cached = await self._cached_get(payload)
            if cached is not None:
                return cached
        await self._limiter.acquire(self._provider, self._model, payload)
        response = await self._generator.run_async(messages=messages, tools=tools, **kwargs)
        if use_cache:
            await self._cached_set(payload, response)
        return response

    def run(self, messages, tools=None, **kwargs):
        payload = dict(kwargs)
        payload["messages"] = messages
        payload["tools"] = tools
        use_cache = not tools
        try:
            asyncio.get_running_loop()
            logger.warning("Skipping synchronous LLM limiter acquire inside running event loop")
        except RuntimeError:
            if use_cache:
                cached = asyncio.run(self._cached_get(payload))
                if cached is not None:
                    return cached
            asyncio.run(self._limiter.acquire(self._provider, self._model, payload))
        response = self._generator.run(messages=messages, tools=tools, **kwargs)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            if use_cache:
                asyncio.run(self._cached_set(payload, response))
        return response

    def __getattr__(self, item: str):
        return getattr(self._generator, item)
