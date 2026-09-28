import json
import time

import httpx

BASE = "http://127.0.0.1:8904"
MCP = f"{BASE}/mcp"
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
    return httpx.post(MCP, json=body, headers=headers, timeout=5.0)


for _ in range(40):
    try:
        if httpx.get(f"{BASE}/health", timeout=1.0).status_code == 200:
            break
    except Exception:
        time.sleep(0.25)

print("good call:", call("tools/call", {"name": "flat_params", "arguments": {"species": "犬"}}, name="flat_params", rid=1).json()["result"].get("isError"))
print("bad call:", call("tools/call", {"name": "flat_params", "arguments": {"species": "恐龙"}}, name="flat_params", rid=2).json()["result"].get("isError"))
