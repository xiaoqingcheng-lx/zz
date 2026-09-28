import inspect

import mcp
import mcp.types as types

# --- find ToolError ---
print("=== search ToolError ===")
import mcp.server.mcpserver as ms

cands = [n for n in dir(ms) if "rror" in n]
print("mcpserver errors:", cands)
for modname in ["mcp.server.mcpserver", "mcp.server.mcpserver.exceptions", "mcp.server.mcpserver.tools", "mcp.shared.exceptions"]:
    try:
        m = __import__(modname, fromlist=["*"])
        print(modname, "->", [n for n in dir(m) if "rror" in n])
    except Exception as e:
        print(modname, "ERR", e)

print("\n=== CallToolResult fields (types) ===")
print(types.CallToolResult.model_fields.keys())
for k, v in types.CallToolResult.model_fields.items():
    print(" ", k, "|", v.annotation, "| default=", v.default)

print("\n=== Tool fields ===")
print(types.Tool.model_fields.keys())
for k, v in types.Tool.model_fields.items():
    print(" ", k, "|", v.annotation, "| default=", v.default)

print("\n=== ListToolsResult fields ===")
print(types.ListToolsResult.model_fields.keys())
for k, v in types.ListToolsResult.model_fields.items():
    print(" ", k, "|", v.annotation, "| default=", v.default)

print("\n=== TextContent fields ===")
print(types.TextContent.model_fields.keys())

print("\n=== Client ===")
print("Client init:", inspect.signature(mcp.Client.__init__))
print("Client public:", [n for n in dir(mcp.Client) if not n.startswith("_")])
