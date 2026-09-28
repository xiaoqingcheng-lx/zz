import inspect

import mcp
import mcp.server as s

print("mcp file:", mcp.__file__)
print("mcp version:", getattr(mcp, "__version__", "n/a"))

print("\n=== mcp.server exports ===")
print([n for n in dir(s) if not n.startswith("_")])

from mcp.server import MCPServer  # noqa: E402

print("\n=== MCPServer.__init__ ===")
print(inspect.signature(MCPServer.__init__))
print("\n=== MCPServer public members ===")
print([n for n in dir(MCPServer) if not n.startswith("_")])
print("\n=== MCPServer.run ===")
print(inspect.signature(MCPServer.run))
print("\n=== MCPServer.streamable_http_app ===")
print(inspect.signature(MCPServer.streamable_http_app))
print("\n=== MCPServer.tool ===")
print(inspect.signature(MCPServer.tool))
print("\n=== MCPServer.custom_route ===")
print(inspect.signature(MCPServer.custom_route))

print("\n=== top-level mcp exports ===")
print([n for n in dir(mcp) if not n.startswith("_")])
