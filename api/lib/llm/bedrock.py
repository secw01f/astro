import json
import re
from dataclasses import replace
from typing import Any

from haystack.dataclasses import ChatMessage
from haystack.dataclasses.chat_message import ToolCallResult

_REGION_PREFIX: dict[str, str] = {
    "us-east-1": "us",
    "us-east-2": "us",
    "us-west-1": "us",
    "us-west-2": "us",
    "eu-central-1": "eu",
    "eu-central-2": "eu",
    "eu-west-1": "eu",
    "eu-west-2": "eu",
    "eu-west-3": "eu",
    "eu-north-1": "eu",
    "eu-south-1": "eu",
    "eu-south-2": "eu",
    "ap-southeast-2": "au",
    "ap-southeast-4": "au",
    "ap-northeast-1": "apac",
    "ap-northeast-2": "apac",
    "ap-northeast-3": "apac",
    "ap-south-1": "apac",
    "ap-south-2": "apac",
    "ap-southeast-1": "apac",
    "ap-southeast-3": "apac",
    "ap-east-1": "apac",
    "ca-central-1": "us",
    "sa-east-1": "us",
}

_PROFILE_PREFIXES = ("us.", "eu.", "global.", "au.", "apac.", "ap.")

def inference_profile_prefix_for_region(region: str | None) -> str:
    if not region:
        return "us"
    normalized = region.strip().lower()
    if normalized in _REGION_PREFIX:
        return _REGION_PREFIX[normalized]
    if normalized.startswith("us-") or normalized.startswith("ca-") or normalized.startswith("sa-"):
        return "us"
    if normalized.startswith("eu-"):
        return "eu"
    if normalized.startswith("ap-southeast-2") or normalized.startswith("ap-southeast-4"):
        return "au"
    if normalized.startswith("ap-"):
        return "apac"
    return "us"

def resolve_bedrock_model_id(model: str, region: str | None) -> str:
    """Return a Bedrock modelId suitable for Converse (inference profile when required)."""
    if not model:
        return model
    if model.startswith("arn:aws:bedrock:") or model.startswith(_PROFILE_PREFIXES):
        return model
    # Legacy on-demand model IDs include a numeric version suffix (e.g. ...-v1:0).
    if re.search(r":\d+$", model):
        return model
    if model.startswith("anthropic."):
        prefix = inference_profile_prefix_for_region(region)
        return f"{prefix}.{model}"
    return model

def _coerce_tool_result_string(result: str) -> str:
    """Bedrock Converse requires toolResult.content[].json to be a JSON object, not array/scalar."""
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        return result
    if isinstance(parsed, dict):
        return result
    return json.dumps({"result": parsed})

def normalize_messages_for_bedrock(messages: list[ChatMessage]) -> list[ChatMessage]:
    normalized: list[ChatMessage] = []
    for message in messages:
        if not message.tool_call_results:
            normalized.append(message)
            continue
        coerced_results: list[ToolCallResult] = []
        for tool_result in message.tool_call_results:
            result = tool_result.result
            if isinstance(result, str):
                result = _coerce_tool_result_string(result)
            coerced_results.append(
                ToolCallResult(result=result, origin=tool_result.origin, error=tool_result.error)
            )
        normalized.append(replace(message, _content=coerced_results))
    return normalized

class BedrockToolResultChatGenerator:
    """Wraps a chat generator so tool results satisfy Bedrock's JSON-object requirement."""

    def __init__(self, generator: Any) -> None:
        self._generator = generator

    def run(self, messages: list[ChatMessage], tools=None, **kwargs):
        return self._generator.run(
            messages=normalize_messages_for_bedrock(messages),
            tools=tools,
            **kwargs,
        )

    async def run_async(self, messages: list[ChatMessage], tools=None, **kwargs):
        return await self._generator.run_async(
            messages=normalize_messages_for_bedrock(messages),
            tools=tools,
            **kwargs,
        )

    def __getattr__(self, item: str):
        return getattr(self._generator, item)