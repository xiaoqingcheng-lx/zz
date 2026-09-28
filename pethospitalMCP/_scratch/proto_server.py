"""Prototype: verify the real mcp 2.0.0 stateless Streamable HTTP behaviour."""

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("Proto", version="0.1.0")


@mcp.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return f"echo:{text}"


@mcp.tool()
def boom() -> str:
    """Always fails with a ToolError."""
    raise ToolError("boom happened")


@mcp.tool()
async def boom_async() -> str:
    """Always raises a plain exception."""
    raise RuntimeError("secret internal detail")


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app(stateless_http=True, json_response=True)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8901, log_level="warning")
