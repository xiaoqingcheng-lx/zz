"""Debug why the middleware does not see tools/call results."""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server import MCPServer

LOG = []


async def normalization_middleware(ctx: Any, call_next: Any) -> Any:
    result = await call_next(ctx)
    LOG.append((getattr(ctx, "method", None), type(result).__name__, repr(result)[:160]))
    print("MW:", getattr(ctx, "method", None), type(result).__name__, repr(result)[:200], flush=True)
    return result


mcp = MCPServer("Proto3", version="0.3.0", middleware=[normalization_middleware])


@mcp.tool(name="flat_params")
async def flat_params(species: Literal["犬", "猫"] | None = None, page: int = Field(default=1, ge=1)) -> str:
    """Flat params."""
    return "ok"


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app(stateless_http=True, json_response=True)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8904, log_level="info")
