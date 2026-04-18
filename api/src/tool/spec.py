import os

from haystack.tools import Toolset, tool

@tool(name="list_specs")
def list_specs() -> list[str]:
    """
    List all specs in the specs directory.
    """
    specs_dir = "/api/specs"
    return [spec for spec in os.listdir(specs_dir) if spec.endswith(".md")]

@tool(name="get_spec")
def get_spec(name: str) -> str:
    """
    Get a spec by name.
    """
    spec_path = f"/api/specs/{name}.md"
    try:
        with open(spec_path, "r") as file:
            return file.read()
    except FileNotFoundError:
        return f"Spec {name} not found"

@tool(name="create_spec")
def create_spec(name: str, content: str) -> str:
    """
    Create a new spec.
    """
    spec_path = f"/api/specs/{name}.md"
    with open(spec_path, "w") as file:
        file.write(content)
    return f"Spec {name} created"

@tool(name="update_spec")
def update_spec(name: str, content: str) -> str:
    """
    Update an existing spec.
    """
    spec_path = f"/api/specs/{name}.md"
    try:
        with open(spec_path, "w") as file:
            file.write(content)
        return f"Spec {name} updated"
    except FileNotFoundError:
        return f"Spec {name} not found"

@tool(name="delete_spec")
def delete_spec(name: str) -> str:
    """
    Delete an existing spec.
    """
    spec_path = f"/api/specs/{name}.md"
    if os.path.exists(spec_path):
        os.remove(spec_path)
        return f"Spec {name} deleted"
    else:
        return f"Spec {name} not found"

def SpecToolset() -> Toolset:
    return Toolset([list_specs, get_spec, create_spec, update_spec, delete_spec])