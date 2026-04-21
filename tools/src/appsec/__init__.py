import asyncio

from fastapi import APIRouter, HTTPException

from lib.models import ToolsResponse, Tool, ExecTool, ExecResponse
from src.appsec.tools import Registry

appsec_router = APIRouter(prefix="/appsec")

@appsec_router.get("/tools")
async def list_tools() -> ToolsResponse:
    return ToolsResponse(
    tools=[
        Tool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input.model_json_schema(),
        )
        for tool in Registry.values()
    ]
)

@appsec_router.post("/exec")
async def exec_tool(exec: ExecTool):
    tool = Registry.get(exec.tool)

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    try:
        result = await asyncio.wait_for(
            tool.func(tool.input(**exec.arguments)),
            timeout=20
        )

        return ExecResponse(result=result)
    
    except Exception as e:
        return ExecResponse(
            result=None,
            error=str(e)
        )
