import os

from haystack.tools import Toolset, tool

SPECS_DIR = "/api/specs"
TEMPLATES_DIR = "templates"
SPEC_TYPE_DIRS = {
    "process": "processes",
    "tooling": "tooling",
    "concept": "concepts",
}
SPEC_TYPE_PREFIXES = {
    "process": "spec_process_",
    "tooling": "spec_tooling_",
    "concept": "spec_concept_",
}
SPEC_TEMPLATE_NAMES = {
    spec_type: f"spec_template_{spec_type}.md" for spec_type in SPEC_TYPE_DIRS
}


def _normalize_spec_type(spec_type: str) -> str | None:
    key = spec_type.strip().lower()
    if key in SPEC_TYPE_DIRS:
        return key
    if key in SPEC_TYPE_DIRS.values():
        for spec_type_name, directory in SPEC_TYPE_DIRS.items():
            if directory == key:
                return spec_type_name
    return None


def _normalize_name(name: str) -> str:
    base = name.strip().removesuffix(".md")
    if "/" in base:
        base = base.rsplit("/", 1)[-1]
    return base


def _spec_basename(spec_type: str, name: str) -> str:
    base = _normalize_name(name)
    prefix = SPEC_TYPE_PREFIXES[spec_type]
    if not base.startswith(prefix):
        base = f"{prefix}{base.removeprefix('spec_')}"
    return f"{base}.md"


def _spec_path(spec_type: str, name: str) -> str:
    return os.path.join(SPECS_DIR, SPEC_TYPE_DIRS[spec_type], _spec_basename(spec_type, name))


def _templates_root() -> str:
    return os.path.join(SPECS_DIR, TEMPLATES_DIR)


def _find_spec_path(name: str) -> str | None:
    base = _normalize_name(name)
    candidates: list[str] = []
    if not base.endswith(".md"):
        candidates.append(f"{base}.md")
    else:
        candidates.append(base)

    for directory in SPEC_TYPE_DIRS.values():
        for candidate in candidates:
            path = os.path.join(SPECS_DIR, directory, candidate)
            if os.path.isfile(path):
                return path
    return None


def _find_template_path(name: str | None = None, spec_type: str | None = None) -> str | None:
    if spec_type is not None:
        normalized_type = _normalize_spec_type(spec_type)
        if normalized_type is None:
            return None
        path = os.path.join(_templates_root(), SPEC_TEMPLATE_NAMES[normalized_type])
        return path if os.path.isfile(path) else None

    if name is None:
        return None

    base = _normalize_name(name)
    candidates: list[str] = []
    if not base.endswith(".md"):
        candidates.append(f"{base}.md")
    else:
        candidates.append(base)

    normalized_type = _normalize_spec_type(base.removeprefix("spec_template_").removesuffix(".md"))
    if normalized_type is not None:
        candidates.append(SPEC_TEMPLATE_NAMES[normalized_type])

    for candidate in dict.fromkeys(candidates):
        path = os.path.join(_templates_root(), candidate)
        if os.path.isfile(path):
            return path
        path = os.path.join(SPECS_DIR, TEMPLATES_DIR, candidate)
        if os.path.isfile(path):
            return path
    return None


def _is_template_path(path: str) -> bool:
    return os.path.commonpath([path, _templates_root()]) == _templates_root()


def _list_spec_files(spec_type: str | None = None, search: str | None = None) -> list[str]:
    results: list[str] = []
    types = [spec_type] if spec_type else list(SPEC_TYPE_DIRS)
    query = search.strip().lower() if search else None

    for spec_type_name in types:
        directory = os.path.join(SPECS_DIR, SPEC_TYPE_DIRS[spec_type_name])
        if not os.path.isdir(directory):
            continue
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".md"):
                continue
            rel_path = f"{SPEC_TYPE_DIRS[spec_type_name]}/{filename}"
            if query and query not in filename.lower() and query not in rel_path.lower():
                continue
            results.append(rel_path)
    return results


def _list_template_files(spec_type: str | None = None, search: str | None = None) -> list[str]:
    directory = _templates_root()
    if not os.path.isdir(directory):
        return []

    query = search.strip().lower() if search else None
    allowed = (
        {SPEC_TEMPLATE_NAMES[spec_type]}
        if spec_type
        else set(SPEC_TEMPLATE_NAMES.values())
    )
    results: list[str] = []
    for filename in sorted(os.listdir(directory)):
        if filename not in allowed or not filename.endswith(".md"):
            continue
        rel_path = f"{TEMPLATES_DIR}/{filename}"
        if query and query not in filename.lower() and query not in rel_path.lower():
            continue
        results.append(rel_path)
    return results


@tool(name="list_specs")
def list_specs(spec_type: str | None = None, search: str | None = None) -> list[str] | str:
    """
    List spec files, optionally filtered by type directory or name search.

    Args:
        spec_type: One of process, tooling, or concept (directory name also accepted).
        search: Case-insensitive substring to match against filenames or paths.
    """
    normalized_type = _normalize_spec_type(spec_type) if spec_type else None
    if spec_type and normalized_type is None:
        valid = ", ".join(sorted(SPEC_TYPE_DIRS))
        return f"Invalid spec_type '{spec_type}'. Use one of: {valid}"
    return _list_spec_files(normalized_type, search)


@tool(name="list_spec_templates")
def list_spec_templates(spec_type: str | None = None, search: str | None = None) -> list[str] | str:
    """
    List spec templates in the templates directory.

    Args:
        spec_type: One of process, tooling, or concept.
        search: Case-insensitive substring to match against filenames or paths.
    """
    normalized_type = _normalize_spec_type(spec_type) if spec_type else None
    if spec_type and normalized_type is None:
        valid = ", ".join(sorted(SPEC_TYPE_DIRS))
        return f"Invalid spec_type '{spec_type}'. Use one of: {valid}"
    return _list_template_files(normalized_type, search)


@tool(name="get_spec_template")
def get_spec_template(spec_type: str) -> str:
    """
    Get the markdown template for a spec type. Use before create_spec.

    Args:
        spec_type: One of process, tooling, or concept.
    """
    normalized_type = _normalize_spec_type(spec_type)
    if normalized_type is None:
        valid = ", ".join(sorted(SPEC_TYPE_DIRS))
        return f"Invalid spec_type '{spec_type}'. Use one of: {valid}"

    template_path = _find_template_path(spec_type=normalized_type)
    if template_path is None:
        return f"Template for {spec_type} not found"
    with open(template_path, "r") as file:
        return file.read()


@tool(name="get_spec")
def get_spec(name: str) -> str:
    """
    Get a spec or template by name or relative path.

    Examples:
        processes/spec_process_example.md
        templates/spec_template_process.md
    """
    spec_path = _find_spec_path(name) or _find_template_path(name=name)
    if spec_path is None:
        return f"Spec {name} not found"
    with open(spec_path, "r") as file:
        return file.read()


@tool(name="create_spec")
def create_spec(spec_type: str, name: str, content: str) -> str:
    """
    Create a new spec in the directory for its type.

    Call get_spec_template(spec_type) first and fill in the template placeholders.

    Args:
        spec_type: One of process, tooling, or concept.
        name: Descriptive name; prefixed automatically if needed (spec_{type}_{name}.md).
        content: Full markdown body for the new spec.
    """
    normalized_type = _normalize_spec_type(spec_type)
    if normalized_type is None:
        valid = ", ".join(sorted(SPEC_TYPE_DIRS))
        return f"Invalid spec_type '{spec_type}'. Use one of: {valid}"

    if not content.strip():
        return "Spec content cannot be empty"

    spec_path = _spec_path(normalized_type, name)
    if os.path.exists(spec_path):
        return f"Spec already exists at {os.path.relpath(spec_path, SPECS_DIR)}"

    basename = os.path.basename(spec_path)
    expected_prefix = SPEC_TYPE_PREFIXES[normalized_type]
    if not basename.startswith(expected_prefix):
        return (
            f"Spec filename must start with '{expected_prefix}' "
            f"(got '{basename}')"
        )

    os.makedirs(os.path.dirname(spec_path), exist_ok=True)
    with open(spec_path, "w") as file:
        file.write(content)
    return f"Spec created at {os.path.relpath(spec_path, SPECS_DIR)}"


@tool(name="update_spec")
def update_spec(
    name: str,
    old_string: str | None = None,
    new_string: str | None = None,
    content: str | None = None,
    replace_all: bool = False,
) -> str:
    """
    Update an existing spec. Prefer partial edits to reduce token usage.

    Provide either:
    - old_string and new_string: replace matching text in the file (default: first match only).
    - content: replace the entire file (use only when a full rewrite is necessary).

    Args:
        name: Spec name or relative path.
        old_string: Text to find in the current spec.
        new_string: Replacement text (required when old_string is set).
        content: Full new file contents (mutually exclusive with old_string/new_string).
        replace_all: When true, replace every occurrence of old_string.
    """
    spec_path = _find_spec_path(name)
    if spec_path is None:
        return f"Spec {name} not found"
    if _is_template_path(spec_path):
        return "Templates are read-only; use create_spec to add a new spec"

    has_patch = old_string is not None or new_string is not None
    has_full = content is not None

    if has_patch and has_full:
        return "Provide either old_string/new_string or content, not both"
    if has_patch:
        if old_string is None:
            return "old_string is required for partial updates"
        if new_string is None:
            return "new_string is required for partial updates"
        with open(spec_path, "r") as file:
            current = file.read()
        if old_string not in current:
            return "old_string not found in spec; read the spec and try again"
        count = current.count(old_string)
        if count > 1 and not replace_all:
            return (
                f"old_string appears {count} times; set replace_all=true "
                "or use a more specific old_string"
            )
        updated = current.replace(old_string, new_string, -1 if replace_all else 1)
        with open(spec_path, "w") as file:
            file.write(updated)
        return f"Spec updated at {os.path.relpath(spec_path, SPECS_DIR)}"

    if has_full:
        with open(spec_path, "w") as file:
            file.write(content)
        return f"Spec updated at {os.path.relpath(spec_path, SPECS_DIR)}"

    return "Provide old_string and new_string for a partial update, or content for a full rewrite"


@tool(name="delete_spec")
def delete_spec(name: str) -> str:
    """
    Delete an existing spec by name or relative path.
    """
    spec_path = _find_spec_path(name)
    if spec_path is None:
        return f"Spec {name} not found"
    if _is_template_path(spec_path):
        return "Templates are read-only and cannot be deleted"
    os.remove(spec_path)
    return f"Spec deleted at {os.path.relpath(spec_path, SPECS_DIR)}"


def SpecToolset() -> Toolset:
    return Toolset([
        list_specs,
        list_spec_templates,
        get_spec_template,
        get_spec,
        create_spec,
        update_spec,
        delete_spec,
    ])
