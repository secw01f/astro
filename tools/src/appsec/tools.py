import httpx
from pydantic import BaseModel
from lib.tool import create_tool_registry

Registry, tool = create_tool_registry("appsec")

class GetInput(BaseModel):
    url: str

class PostInput(BaseModel):
    url: str
    json: dict | None = None
    form: dict[str, str | int | float | bool] | None = None

class PutInput(BaseModel):
    url: str
    json: dict | None = None
    form: dict[str, str | int | float | bool] | None = None

class PatchInput(BaseModel):
    url: str
    json: dict | None = None
    form: dict[str, str | int | float | bool] | None = None

class DeleteInput(BaseModel):
    url: str

@tool(name="get", description="Get from a URL", capabilities=["get"], version="1.0")
async def get(input: GetInput) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(input.url)
    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "content": response.text,
        }

@tool(name="post", description="Post to a URL", capabilities=["post"], version="1.0")
async def post(input: PostInput) -> dict:
    if input.json is not None and input.form is not None:
        return {
            "error": "Provide either json or form (multipart), not both."
        }

    async with httpx.AsyncClient() as client:
        if input.form is not None:
            form_data = {key: str(value) for key, value in input.form.items()}
            response = await client.post(input.url, files=form_data)
        else:
            response = await client.post(input.url, json=input.json or {})

    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "content": response.text,
        }

@tool(name="put", description="Put to a URL", capabilities=["put"], version="1.0")
async def put(input: PutInput) -> dict:
    if input.json is not None and input.form is not None:
        return {
            "error": "Provide either json or form (multipart), not both."
        }

    async with httpx.AsyncClient() as client:
        if input.form is not None:
            form_data = {key: str(value) for key, value in input.form.items()}
            response = await client.put(input.url, files=form_data)
        else:
            response = await client.put(input.url, json=input.json or {})

    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "content": response.text,
        }

@tool(name="patch", description="Patch to a URL", capabilities=["patch"], version="1.0")
async def patch(input: PatchInput) -> dict:
    if input.json is not None and input.form is not None:
        return {
            "error": "Provide either json or form (multipart), not both."
        }

    async with httpx.AsyncClient() as client:
        if input.form is not None:
            form_data = {key: str(value) for key, value in input.form.items()}
            response = await client.patch(input.url, files=form_data)
        else:
            response = await client.patch(input.url, json=input.json or {})

    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "content": response.text,
        }

@tool(name="delete", description="Delete from a URL", capabilities=["delete"], version="1.0")
async def delete(input: DeleteInput) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.delete(input.url)
    return response.json()

    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "content": response.text,
        }