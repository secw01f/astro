import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from lib.models import ExecResponse, ExecTool, Tool, ToolsResponse
from src.threatmodel.tools import Registry

threatmodel_router = APIRouter(prefix="/threatmodel")
logger = logging.getLogger(__name__)


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
        tool_input = t.input(**exec.arguments)
        result = await asyncio.wait_for(
            t.func(tool_input),
            timeout=20,
        )

        return ExecResponse(result=result)

    except ValidationError:
        return ExecResponse(result=None, error="Invalid tool arguments")
    except asyncio.TimeoutError:
        return ExecResponse(result=None, error="Tool execution timed out")
    except Exception as e:
        logger.exception("Unexpected threatmodel tool failure: %s", exec.tool)
        raise HTTPException(status_code=500, detail="Tool execution failed") from e
