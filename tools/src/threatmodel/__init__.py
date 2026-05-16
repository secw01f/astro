import asyncio

from fastapi import APIRouter, HTTPException

from lib.models import ExecResponse, ExecTool, Tool, ToolsResponse
from src.threatmodel.tools import Registry

threatmodel_router = APIRouter(prefix="/threatmodel")


@threatmodel_router.get("/tools")
async def list_tools() -> ToolsResponse:
    return ToolsResponse(
        tools=[
            Tool(
                name=t.name,
                description=t.description,
                input_schema=t.input.model_json_schema(),
            )
            for t in Registry.values()
        ]
    )


@threatmodel_router.post("/exec")
async def exec_tool(exec: ExecTool):
    t = Registry.get(exec.tool)

    if not t:
        raise HTTPException(status_code=404, detail="Tool not found")

    try:
        result = await asyncio.wait_for(
            t.func(t.input(**exec.arguments)),
            timeout=20,
        )

        return ExecResponse(result=result)

    except Exception as e:
        return ExecResponse(result=None, error=str(e))
