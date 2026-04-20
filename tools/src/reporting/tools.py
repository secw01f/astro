from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from pydantic import BaseModel, Field

from lib.tool import create_tool_registry

Registry, tool = create_tool_registry("reporting")

REPORTS_DIR = Path("/tmp/astro-reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "report"


def _report_path(name: str) -> Path:
    safe_name = _safe_name(name)
    if not safe_name.endswith(".md"):
        safe_name = f"{safe_name}.md"
    return REPORTS_DIR / safe_name


class BuildReportInput(BaseModel):
    title: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    report_type: str = "security_assessment"
    author: str = "astro"
    tags: list[str] = Field(default_factory=list)


class SaveReportInput(BaseModel):
    name: str
    content: str
    overwrite: bool = False


class GetReportInput(BaseModel):
    name: str


class AppendSectionInput(BaseModel):
    name: str
    heading: str
    content: str


class ListReportsInput(BaseModel):
    limit: int = 50


@tool(
    name="build_markdown_report",
    description="Build a structured markdown report from findings",
    capabilities=["reporting"],
    version="1.0",
)
async def build_markdown_report(input: BuildReportInput) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    findings_md = (
        "\n".join(f"- {finding}" for finding in input.findings)
        if input.findings
        else "- No findings were provided."
    )
    recommendations_md = (
        "\n".join(f"- {recommendation}" for recommendation in input.recommendations)
        if input.recommendations
        else "- No recommendations were provided."
    )
    tags_md = ", ".join(input.tags) if input.tags else "none"

    markdown = (
        f"# {input.title}\n\n"
        f"## Metadata\n"
        f"- Report Type: {input.report_type}\n"
        f"- Author: {input.author}\n"
        f"- Created: {created_at}\n"
        f"- Tags: {tags_md}\n\n"
        f"## Executive Summary\n"
        f"{input.summary}\n\n"
        f"## Findings\n"
        f"{findings_md}\n\n"
        f"## Recommendations\n"
        f"{recommendations_md}\n"
    )

    return {
        "title": input.title,
        "created": created_at,
        "content": markdown,
        "length": len(markdown),
    }


@tool(
    name="save_report",
    description="Persist a markdown report to local storage",
    capabilities=["reporting"],
    version="1.0",
)
async def save_report(input: SaveReportInput) -> dict:
    path = _report_path(input.name)
    if path.exists() and not input.overwrite:
        return {
            "saved": False,
            "path": str(path),
            "error": "Report already exists. Set overwrite=true to replace it.",
        }

    path.write_text(input.content, encoding="utf-8")
    return {"saved": True, "path": str(path), "bytes": path.stat().st_size}


@tool(
    name="get_report",
    description="Read a saved report by name",
    capabilities=["reporting"],
    version="1.0",
)
async def get_report(input: GetReportInput) -> dict:
    path = _report_path(input.name)
    if not path.exists():
        return {"found": False, "path": str(path), "error": "Report not found"}

    content = path.read_text(encoding="utf-8")
    return {"found": True, "path": str(path), "content": content, "length": len(content)}


@tool(
    name="append_report_section",
    description="Append a new section to an existing report",
    capabilities=["reporting"],
    version="1.0",
)
async def append_report_section(input: AppendSectionInput) -> dict:
    path = _report_path(input.name)
    if not path.exists():
        return {"updated": False, "path": str(path), "error": "Report not found"}

    section = f"\n\n## {input.heading}\n{input.content}\n"
    with path.open("a", encoding="utf-8") as file:
        file.write(section)

    return {"updated": True, "path": str(path), "appended_chars": len(section)}


@tool(
    name="list_reports",
    description="List recently modified reports",
    capabilities=["reporting"],
    version="1.0",
)
async def list_reports(input: ListReportsInput) -> list[dict]:
    report_files = sorted(
        REPORTS_DIR.glob("*.md"),
        key=lambda report: report.stat().st_mtime,
        reverse=True,
    )[: max(1, input.limit)]

    reports: list[dict] = []
    for report in report_files:
        stats = report.stat()
        reports.append(
            {
                "name": report.name,
                "path": str(report),
                "bytes": stats.st_size,
                "modified": datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    return reports
