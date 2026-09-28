import inspect

import mcp
import mcp.types as types

print("=== DiscoverResult ===")
try:
    print(types.DiscoverResult.model_fields.keys())
    for k, v in types.DiscoverResult.model_fields.items():
        print("  ", k, "|", v.annotation, "| default=", v.default)
except Exception as e:
    print("ERR", e)

print("\n=== protocol version constants ===")
for n in dir(types):
    if "PROTOCOL" in n.upper() or "VERSION" in n.upper() or n.startswith("LATEST"):
        print("  ", n, "=", getattr(types, n))

print("\n=== mcp.client.streamable_http ===")
import mcp.client.streamable_http as sth

print([n for n in dir(sth) if not n.startswith("_")])
for n in dir(sth):
    if not n.startswith("_") and callable(getattr(sth, n)) and "client" in n.lower():
        try:
            print("  sig", n, inspect.signature(getattr(sth, n)))
        except Exception:
            pass

print("\n=== mcp.client.Transport ===")
from mcp.client import Transport  # noqa: E402

print(Transport)
print(getattr(Transport, "__args__", None))

print("\n=== discover-related types ===")
for n in dir(types):
    if "iscover" in n:
        obj = getattr(types, n)
        print("  ", n, getattr(obj, "model_fields", {}).keys() if hasattr(obj, "model_fields") else obj)
