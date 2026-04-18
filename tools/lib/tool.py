import importlib
import pkgutil

from lib.models import ToolDef

def create_tool_registry(namespace: str):

    registry = {}

    def tool(name: str, description: str, capabilities: list[str] | None = None, version: str = "0.1"):
        def tool_wrapper(func):
            _input = func.__annotations__.get("input")
            
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

def loader(base_package="src"):
    registries = []

    package = importlib.import_module(base_package)

    for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__):

        if not is_pkg:
            continue

        try:
            tools_module = importlib.import_module(
                f"{base_package}.{module_name}.tools"
            )

            registry = getattr(tools_module, "Registry", None)

            if registry:
                registries.append(registry)

        except ModuleNotFoundError:
            continue

    return registries