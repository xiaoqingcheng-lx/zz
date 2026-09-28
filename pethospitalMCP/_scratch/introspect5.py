import inspect

import mcp.server.streamable_http as sth
import mcp.server.mcpserver as ms

print("=== mcp.server.streamable_http names ===")
print([n for n in dir(sth) if not n.startswith("_")])

for n in ["MCP_PROTOCOL_VERSION_HEADER", "MCP_METHOD_HEADER", "MCP_NAME_HEADER", "MCP_SESSION_ID"]:
    print(n, "=", getattr(sth, n, "<missing>"))

from mcp.client.streamable_http import MODERN_PROTOCOL_VERSIONS  # noqa: E402

print("MODERN_PROTOCOL_VERSIONS =", MODERN_PROTOCOL_VERSIONS)

print("\n=== MCPServer.discover / handlers ===")
print([n for n in dir(ms) if "iscover" in n or "Method" in n or "METHOD" in n])

print("\n=== search 'server/discover' in mcpserver source ===")
src = inspect.getsource(ms)
for i, line in enumerate(src.splitlines(), 1):
    if "discover" in line.lower():
        print(i, line)
