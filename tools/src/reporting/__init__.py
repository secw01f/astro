import asyncio

from fastapi import APIRouter, HTTPException, Request

from lib.context import reset_user_id, set_user_id
from lib.models import ToolsResponse, Tool, ExecTool, ExecResponse
from src.reporting.tools import Registry

reporting_router = APIRouter(prefix="/reporting")

@reporting_router.get("/tools")
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

@reporting_router.post("/exec")
async def exec_tool(exec: ExecTool, request: Request):
    tool = Registry.get(exec.tool)

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    user_id = getattr(request.state, "user_id", None)
    token = set_user_id(user_id)
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
    finally:
        reset_user_id(token)
