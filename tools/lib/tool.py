from typing import get_type_hints

from lib.models import ToolDef

def create_tool_registry(namespace: str):

    registry = {}

    def tool(name: str, description: str, capabilities: list[str] | None = None, version: str = "0.1"):
        def tool_wrapper(func):
            hints = get_type_hints(func, globalns=func.__globals__, localns=None)
            _input = hints.get("input")
            if _input is None:
                raise TypeError(f"Tool {namespace}.{name} must type-annotate its input parameter")
            
            registry[name] = ToolDef(
                name = name,
                description = description,
                version = version,
                namespace = namespace,
                capabilities = capabilities or [],
                func = func,
                input = _input
            )

            return func
        return tool_wrapper
    return registry, tool
