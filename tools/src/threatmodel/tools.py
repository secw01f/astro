from __future__ import annotations

from typing import Any

from lark import Lark, UnexpectedInput
from lark.visitors import Transformer, v_args
from pydantic import BaseModel, Field

from lib.tool import create_tool_registry

Registry, tool = create_tool_registry("threatmodel")

_STRIDE_TOKENS: tuple[str, ...] = (
    "spoofing",
    "tampering",
    "repudiation",
    "information_disclosure",
    "denial_of_service",
    "elevation_of_privilege",
)

_STRIDE_SUMMARY: dict[str, str] = {
    "spoofing": "Impersonating something or someone else (identity, source, or rights).",
    "tampering": "Modifying data, code, configuration, or messages without authorization.",
    "repudiation": "Denying having performed an action when accountability is required.",
    "information_disclosure": "Exposing information to actors who should not see or use it.",
    "denial_of_service": "Making a system or resource unavailable to legitimate users.",
    "elevation_of_privilege": "Gaining capabilities or access beyond what was intended.",
}

# Compact line-oriented DSL for sketching components, trust boundaries,
# data flows, and STRIDE-tagged threats. Agents can emit this text and
# consume the structured JSON downstream.
_THREAT_MODEL_GRAMMAR = (
    r"""
start: _NEWLINE* stmt (_NEWLINE+ stmt)* _NEWLINE*

?stmt: component | boundary | flow | threat

component: "component" NAME STRING?
boundary: "boundary" NAME STRING?
flow: "flow" NAME "->" NAME STRING?
threat: "threat" NAME ":" STRIDE STRING?

STRIDE: """
    + " | ".join(f'"{s}"' for s in _STRIDE_TOKENS)
    + r"""

NAME: /[a-zA-Z_][a-zA-Z0-9._-]*/
STRING: /"(?:[^"\\]|\\.)*"/

%import common.WS
%import common.NEWLINE -> _NEWLINE
%ignore WS
"""
)


def _unquote(s: str) -> str:
    inner = s[1:-1]
    return inner.replace('\\"', '"').replace("\\\\", "\\")


@v_args(inline=True)
class _ThreatModelTransformer(Transformer):
    def component(self, name: Any, description: Any | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "component",
            "id": str(name),
        }
        if description is not None:
            out["description"] = _unquote(str(description))
        return out

    def boundary(self, name: Any, description: Any | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "boundary",
            "id": str(name),
        }
        if description is not None:
            out["description"] = _unquote(str(description))
        return out

    def flow(self, source: Any, target: Any, description: Any | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "flow",
            "source": str(source),
            "target": str(target),
        }
        if description is not None:
            out["description"] = _unquote(str(description))
        return out

    def threat(
        self,
        component: Any,
        stride: Any,
        description: Any | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "threat",
            "component": str(component),
            "stride": str(stride),
        }
        if description is not None:
            out["description"] = _unquote(str(description))
        return out

    def start(self, *statements: dict[str, Any]) -> list[dict[str, Any]]:
        return list(statements)


_parser = Lark(
    _THREAT_MODEL_GRAMMAR,
    parser="lalr",
    maybe_placeholders=False,
)


class ParseThreatModelDslInput(BaseModel):
    dsl: str = Field(
        description=(
            "Threat model sketch in the line-oriented DSL. "
            'Example:\ncomponent api "Public REST API"\n'
            'boundary dmz "Perimeter"\n'
            'flow user -> api "HTTPS; OAuth access tokens"\n'
            'threat api : tampering "JWT claim manipulation"'
        ),
    )


@tool(
    name="parse_threat_model_dsl",
    description=(
        "Parse a small threat-modeling DSL (components, boundaries, flows, STRIDE threats) "
        "into structured JSON using Lark. Returns statements or a syntax error with position."
    ),
    capabilities=["threat_modeling", "parse"],
    version="1.0",
)
async def parse_threat_model_dsl(input: ParseThreatModelDslInput) -> dict[str, Any]:
    text = input.dsl.strip()
    if not text:
        return {"statements": [], "raw": input.dsl}

    try:
        tree = _parser.parse(text)
    except UnexpectedInput as e:
        return {
            "error": e.args[0] if e.args else "Unexpected input",
            "line": e.line,
            "column": e.column,
            "context": getattr(e, "context", None),
        }

    statements = _ThreatModelTransformer().transform(tree)
    return {"statements": statements, "raw": input.dsl}


class ThreatModelDslGrammarInput(BaseModel):
    include_lark_grammar: bool = Field(
        default=False,
        description="If true, include the full Lark grammar source string under lark_grammar.",
    )


def _threat_model_dsl_reference(*, include_lark_grammar: bool) -> dict[str, Any]:
    statement_types: list[dict[str, Any]] = [
        {
            "kind": "component",
            "keywords": ["component"],
            "syntax": 'component NAME [STRING]',
            "fields": [
                {"name": "id", "role": "NAME", "description": "Stable identifier for the component (e.g. api, user_db)."},
                {
                    "name": "description",
                    "role": "STRING",
                    "required": False,
                    "description": "Human-readable label or notes in double quotes; escape internal quotes as \\\".",
                },
            ],
            "parse_output": {"kind": "component", "id": "…", "description": "optional"},
            "example": 'component api "Public REST API"',
        },
        {
            "kind": "boundary",
            "keywords": ["boundary"],
            "syntax": 'boundary NAME [STRING]',
            "fields": [
                {"name": "id", "role": "NAME", "description": "Identifier for the trust boundary (e.g. dmz, corp_net)."},
                {
                    "name": "description",
                    "role": "STRING",
                    "required": False,
                    "description": "What this boundary separates or enforces.",
                },
            ],
            "parse_output": {"kind": "boundary", "id": "…", "description": "optional"},
            "example": 'boundary dmz "Internet-facing perimeter"',
        },
        {
            "kind": "flow",
            "keywords": ["flow"],
            "syntax": 'flow NAME "->" NAME [STRING]',
            "fields": [
                {"name": "source", "role": "NAME", "description": "Origin component id (must match a component id you use elsewhere)."},
                {"name": "target", "role": "NAME", "description": "Destination component id."},
                {
                    "name": "description",
                    "role": "STRING",
                    "required": False,
                    "description": "Channel, protocol, or data carried (e.g. HTTPS, OAuth tokens).",
                },
            ],
            "parse_output": {"kind": "flow", "source": "…", "target": "…", "description": "optional"},
            "example": 'flow user -> api "HTTPS; OAuth access tokens"',
        },
        {
            "kind": "threat",
            "keywords": ["threat"],
            "syntax": 'threat NAME ":" STRIDE [STRING]',
            "fields": [
                {"name": "component", "role": "NAME", "description": "Component id this threat applies to."},
                {
                    "name": "stride",
                    "role": "STRIDE",
                    "required": True,
                    "description": "One lowercase STRIDE token; see stride_categories.",
                },
                {
                    "name": "description",
                    "role": "STRING",
                    "required": False,
                    "description": "Concrete threat scenario or attack note.",
                },
            ],
            "parse_output": {"kind": "threat", "component": "…", "stride": "…", "description": "optional"},
            "example": 'threat api : tampering "JWT claim manipulation"',
        },
    ]

    stride_categories = [
        {
            "token": t,
            "summary": _STRIDE_SUMMARY[t],
        }
        for t in _STRIDE_TOKENS
    ]

    tokens: list[dict[str, Any]] = [
        {
            "name": "NAME",
            "pattern": r"[a-zA-Z_][a-zA-Z0-9._-]*",
            "description": "Unquoted identifier for components, boundaries, and flow endpoints.",
        },
        {
            "name": "STRING",
            "pattern": r'"(?:[^"\\]|\\.)*"',
            "description": "Double-quoted literal; use \\\" for quotes inside the string.",
        },
        {
            "name": "STRIDE",
            "values": list(_STRIDE_TOKENS),
            "description": "Exactly one STRIDE category token, lowercase, as listed in stride_categories.",
        },
    ]

    out: dict[str, Any] = {
        "document": {
            "format": "line_oriented",
            "rules": [
                "Each non-empty line is one statement: component, boundary, flow, or threat.",
                "Statements are separated by one or more newlines; leading and trailing blank lines are ignored.",
                "Horizontal whitespace outside quoted strings is ignored.",
                "Keywords are lowercase and fixed (component, boundary, flow, threat).",
                "Use parse_threat_model_dsl to validate and obtain structured JSON.",
            ],
        },
        "statement_types": statement_types,
        "stride_categories": stride_categories,
        "tokens": tokens,
    }

    if include_lark_grammar:
        out["lark_grammar"] = _THREAT_MODEL_GRAMMAR.strip()

    return out


@tool(
    name="get_threat_model_dsl_grammar",
    description=(
        "List and define every grammar element for the threat-model DSL (statement shapes, "
        "STRIDE tokens, NAME/STRING rules, document layout). Use before authoring text for parse_threat_model_dsl."
    ),
    capabilities=["threat_modeling", "reference"],
    version="1.0",
)
async def get_threat_model_dsl_grammar(input: ThreatModelDslGrammarInput) -> dict[str, Any]:
    return _threat_model_dsl_reference(include_lark_grammar=input.include_lark_grammar)
