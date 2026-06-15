import json
import logging
import asyncio
import time
from typing import Any

from haystack.components.agents import Agent
from haystack.dataclasses import ChatMessage
from haystack.tools import ComponentTool, Tool, Toolset
from haystack.components.tools import ToolInvoker

_agent_logger = logging.getLogger("haystack.components.agents.agent")

_TOOL_STREAM_PREVIEW_CHARS = 2000

def _preview_stream_text(text: str, max_chars: int = _TOOL_STREAM_PREVIEW_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "... [truncated]"

def _stringify_tool_result_content(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts: list[str] = []
        for part in result:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                parts.append(text)
            else:
                parts.append(str(part))
        return "\n".join(parts)
    return str(result)

def _serialize_tool_call_result(tcr: Any) -> dict[str, Any]:
    origin = getattr(tcr, "origin", None)
    tool_name = getattr(origin, "tool_name", None) if origin is not None else None
    tool_call_id = getattr(origin, "id", None) if origin is not None else None
    args_preview = ""
    if origin is not None:
        args = getattr(origin, "arguments", None)
        if args is not None:
            try:
                args_preview = _preview_stream_text(json.dumps(args, default=str))
            except Exception:
                args_preview = _preview_stream_text(str(args))
    result_raw = getattr(tcr, "result", None)
    result_preview = _preview_stream_text(_stringify_tool_result_content(result_raw))
    return {
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "arguments_preview": args_preview,
        "result_preview": result_preview,
        "error": bool(getattr(tcr, "error", False)),
    }

class StreamingCallback:
    def __init__(
        self,
        name: str,
        queue: asyncio.Queue,
        run_id: str,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.name = name
        self.queue = queue
        self.run_id = run_id
        self._loop = loop
        self.started = False
        self._streamed_text = False

    def _enqueue(self, item: dict) -> None:
        if self._loop is None:
            self.queue.put_nowait(item)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self.queue.put_nowait(item)
        else:
            self._loop.call_soon_threadsafe(self.queue.put_nowait, item)

    def __call__(self, chunk):
        if getattr(chunk, "tool_call_result", None) is not None:
            if not self.started:
                self.started = True
                self._enqueue({
                    "type": "start",
                    "agent": self.name,
                    "run_id": self.run_id,
                    "timestamp": time.time(),
                })
            payload = {
                "type": "tool_result",
                "agent": self.name,
                "run_id": self.run_id,
                "timestamp": time.time(),
                **_serialize_tool_call_result(chunk.tool_call_result),
            }
            finish_reason = getattr(chunk, "finish_reason", None)
            if finish_reason is not None:
                payload["finish_reason"] = finish_reason
            self._enqueue(payload)
            return

        if chunk.start and not self.started:
            self.started = True
            self._enqueue({
                "type": "start",
                "agent": self.name,
                "run_id": self.run_id,
                "timestamp": time.time(),
            })

        if chunk.content:
            if not self.started:
                self.started = True
                self._enqueue({
                    "type": "start",
                    "agent": self.name,
                    "run_id": self.run_id,
                    "timestamp": time.time(),
                })
            self._enqueue({
                "type": "token",
                "agent": self.name,
                "run_id": self.run_id,
                "content": chunk.content,
                "timestamp": time.time(),
            })
            self._streamed_text = True

    def emit_final_assistant_text(self, text: str | None) -> None:
        if not text:
            return
        if not self.started:
            self.started = True
            self._enqueue({
                "type": "start",
                "agent": self.name,
                "run_id": self.run_id,
                "timestamp": time.time(),
            })
        self._enqueue({
            "type": "response",
            "agent": self.name,
            "run_id": self.run_id,
            "content": text,
            "timestamp": time.time(),
        })
        self._streamed_text = True

    def end(self):
        if not self.started:
            self.started = True
            self._enqueue({
                "type": "start",
                "agent": self.name,
                "run_id": self.run_id,
                "timestamp": time.time(),
            })
        self._enqueue({
            "type": "end",
            "agent": self.name,
            "run_id": self.run_id,
            "timestamp": time.time(),
        })

class SupervisorAgent(Agent):
    def __init__(self, **kwargs):
        init_log_level = _agent_logger.level
        _agent_logger.setLevel(logging.ERROR)

        super().__init__(**kwargs)

        _agent_logger.setLevel(init_log_level)

    def register_supporting_agent(self, agent):
        if not isinstance(agent, SupportingAgent):
            raise TypeError(f"Expected a SupportingAgent but got {type(agent).__name__}.")
        self.tools.append(agent.component_tool)
        self._tool_invoker = ToolInvoker(
            tools=self.tools,
            raise_on_failure=self.raise_on_tool_invocation_failure,
            **(self.tool_invoker_kwargs or {}),
        )

    def add_tool(self, tool: ComponentTool | Toolset | Tool):
        self.tools.append(tool)
        self._tool_invoker = ToolInvoker(
            tools=self.tools,
            raise_on_failure=self.raise_on_tool_invocation_failure,
            **(self.tool_invoker_kwargs or {}),
        )

class SupportingAgent(Agent):
    def __init__(self, name: str, description: str, **kwargs):
        self._agent_name = name
        self._agent_description = description

        super().__init__(**kwargs)

    @staticmethod
    def _args_kwargs_for_agent_run(args: tuple, kwargs: dict):
        kwargs = dict(kwargs)
        if args:
            return args, kwargs
        if "messages" in kwargs:
            return (), kwargs
        if "prompt" in kwargs:
            kwargs = dict(kwargs)
            if "messages" not in kwargs:
                kwargs["messages"] = [ChatMessage.from_user(kwargs["prompt"])]
            return (), kwargs
        raise TypeError(
            "SupportingAgent.run() missing required argument: 'messages' "
            "(or tool-style 'prompt')"
        )

    def run(self, *args, **kwargs):
        args, kwargs = self._args_kwargs_for_agent_run(args, kwargs)
        return super().run(*args, **kwargs)

    async def run_async(self, *args, **kwargs):
        args, kwargs = self._args_kwargs_for_agent_run(args, kwargs)
        return await super().run_async(*args, **kwargs)

    @property
    def component_tool(self):
        if not hasattr(self, "_component_tool"):
            description = (self._agent_description or "").strip() or (
                f"Delegate a task to the {self._agent_name} supporting agent."
            )
            self._component_tool = ComponentTool(
                name=self._agent_name,
                description=description,
                component=self,
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The user_prompt provided to the Supporting Agent by the Supervisor Agent.",
                        }
                    },
                    "required": ["prompt"],
                },

                inputs_from_state={},
                outputs_to_string={"source": "last_message"},
            )
        return self._component_tool
