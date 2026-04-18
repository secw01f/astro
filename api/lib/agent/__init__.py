import logging
import asyncio
import time

from haystack.components.agents import Agent
from haystack.tools import ComponentTool, Tool, Toolset
from haystack.components.tools import ToolInvoker

_agent_logger = logging.getLogger("haystack.components.agents.agent")

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
        if chunk.tool_call_result is not None:
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
        else:
            agent
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

    @property
    def component_tool(self):
        if not hasattr(self, "_component_tool"):
            self._component_tool = ComponentTool(
                name=self._agent_name,
                description=self._agent_description,
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