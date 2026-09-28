import json

import httpx

BASE = "http://127.0.0.1:8904"
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "probe", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def call(method, params, name=None, rid=1):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if name:
        headers["Mcp-Name"] = name
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": {**params, "_meta": META}}
    return httpx.post(f"{BASE}/mcp", json=body, headers=headers, timeout=5.0)


for label, args in [
    ("unknown field", {"species": "犬", "totally_unknown": 1}),
    ("wrong scalar type", {"page": "abc"}),
    ("negative page", {"page": 0}),
    ("float page", {"page": 1.5}),
    ("nan string", {"page": "NaN"}),
]:
    r = call("tools/call", {"name": "flat_params", "arguments": args}, name="flat_params", rid=1).json()
    res = r.get("result", {})
    print(f"{label:18} -> isError={res.get('isError')} | {str(res.get('content'))[:150]}")
