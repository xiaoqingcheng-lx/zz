import inspect

import mcp
import mcp.types as types
import mcp.client as c

print("=== mcp.client exports ===")
print([n for n in dir(c) if not n.startswith("_")])

print("\n=== ConnectMode ===")
from mcp.client import ConnectMode  # noqa: E402

print(ConnectMode, list(getattr(ConnectMode, "__args__", [])))

print("\n=== DiscoverResult ===")
print(types.DiscoverResult.model_fields.keys())
for k, v in types.DiscoverResult.model_fields.items():
    print(" ", k, "|", v.annotation, "| default=", v.default)

print("\n=== Client.call_tool sig ===")
print(inspect.signature(mcp.Client.call_tool))
print("\n=== Client.list_tools sig ===")
print(inspect.signature(mcp.Client.list_tools))
print("\n=== Client protocol_version ===")
print(inspect.getsource(type(mcp.Client).protocol_version.fget) if isinstance(type(mcp.Client).protocol_version, property) else "")

print("\n=== LATEST_PROTOCOL_VERSION / SUPPORTED ===")
import mcp_types  # noqa: E402

for n in dir(types):
    if "PROTOCOL" in n.upper() or "VERSION" in n.upper():
        print(" ", n, "=", getattr(types, n))

print("\n=== Dispatcher / method constants ===")
for n in dir(types):
    if n in ("DiscoverRequest", "DiscoverRequestParams"):
        print(n, types.__dict__[n].model_fields.keys())
