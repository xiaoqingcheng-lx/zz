import inspect

import mcp.server.mcpserver as ms

print("=== ServerMiddleware ===")
import mcp.server.mcpserver.middleware as mw  # noqa: E402

print([n for n in dir(mw) if not n.startswith("_")])
for n in dir(mw):
    if not n.startswith("_") and inspect.isclass(getattr(mw, n)):
        obj = getattr(mw, n)
        try:
            print("\n---", n, inspect.signature(obj))
            for m in dir(obj):
                if not m.startswith("_") and callable(getattr(obj, m)):
                    try:
                        print("    .", m, inspect.signature(getattr(obj, m)))
                    except Exception:
                        print("    .", m)
        except Exception as e:
            print("---", n, "ERR", e)

print("\n=== MCPServer.add_tool ===")
print(inspect.signature(ms.MCPServer.add_tool))
print("\n=== MCPServer.call_tool ===")
print(inspect.signature(ms.MCPServer.call_tool))
print("\n=== MethodBinding ===")
print(inspect.signature(ms.MethodBinding))
print(ms.MethodBinding.__doc__)
