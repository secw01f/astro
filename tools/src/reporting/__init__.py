import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from lib.context import reset_user_id, set_user_id
from lib.models import ToolsResponse, Tool, ExecTool, ExecResponse
from src.reporting.tools import Registry

reporting_router = APIRouter(prefix="/reporting")
logger = logging.getLogger(__name__)

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
        tool_input = tool.input(**exec.arguments)
        result = await asyncio.wait_for(
            tool.func(tool_input),
            timeout=20
        )

        return ExecResponse(result=result)

    except ValidationError:
        return ExecResponse(result=None, error="Invalid tool arguments")
    except asyncio.TimeoutError:
        return ExecResponse(result=None, error="Tool execution timed out")
    except Exception as e:
        logger.exception("Unexpected reporting tool failure: %s", exec.tool)
        raise HTTPException(status_code=500, detail="Tool execution failed") from e
    finally:
        reset_user_id(token)
