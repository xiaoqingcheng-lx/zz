"""Prototype 2: schema shape + middleware-based error normalisation."""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

ENVELOPE_MARKER = '"error"'


def error_envelope(code: str, message: str, details: dict | None = None) -> str:
    return json.dumps({"error": {"code": code, "message": message, "details": details or {}}}, ensure_ascii=False)


async def normalization_middleware(ctx: Any, call_next: Any) -> Any:
    """Turn any framework-produced is_error result into the unified envelope."""
    result = await call_next(ctx)
    if ctx.method == "tools/call" and isinstance(result, CallToolResult) and result.is_error:
        texts = [b.text for b in result.content if isinstance(b, TextContent)]
        raw = "\n".join(texts)
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "error" in parsed:
                return result  # already ours
        except Exception:
            pass
        return CallToolResult(
            content=[TextContent(type="text", text=error_envelope("VALIDATION_ERROR", "Invalid input."))],
            is_error=True,
        )
    return result


mcp = MCPServer("Proto2", version="0.2.0", middleware=[normalization_middleware])

Species = Literal["犬", "猫", "兔"]
SortBy = Literal["id", "name", "totalCost"]


class Filters(BaseModel):
    """Single Pydantic-model parameter."""

    model_config = ConfigDict(extra="forbid")

    species: Species | None = None
    page: int = Field(default=1, ge=1)


class ListOut(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    pageSize: int
    totalPages: int
    totalCost: float


@mcp.tool(name="model_param")
async def model_param(filters: Filters) -> ListOut:
    """Tool taking one Pydantic model parameter."""
    return ListOut(items=[], total=0, page=1, pageSize=20, totalPages=0, totalCost=0.0)


@mcp.tool(name="flat_params")
async def flat_params(
    species: Species | None = None,
    page: int = Field(default=1, ge=1),
    pageSize: int = Field(default=20, ge=1, le=500),
) -> ListOut:
    """Tool with flat typed parameters."""
    return ListOut(items=[], total=0, page=page, pageSize=pageSize, totalPages=0, totalCost=0.0)


@mcp.tool(name="raises_tool_error")
async def raises_tool_error() -> str:
    """Raises ToolError carrying our envelope."""
    raise ToolError(error_envelope("BACKEND_TIMEOUT", "upstream timed out"))


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app(stateless_http=True, json_response=True)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8902, log_level="warning")
