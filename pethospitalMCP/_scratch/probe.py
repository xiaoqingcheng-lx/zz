"""Raw HTTP probe of the prototype MCP endpoint (correct 2026-07-28 envelope)."""

import json
import time

import httpx

BASE = "http://127.0.0.1:8901"
MCP = f"{BASE}/mcp"

META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "probe", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def show(title, resp):
    print(f"\n===== {title} =====")
    print("HTTP", resp.status_code)
    for k, v in resp.headers.items():
        if k.lower().startswith("mcp") or k.lower() in ("content-type",):
            print("  H:", k, "=", v)
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2)[:3000])
    except Exception:
        print(resp.text[:1500])


for _ in range(40):
    try:
        if httpx.get(f"{BASE}/health", timeout=1.0).status_code == 200:
            break
    except Exception:
        time.sleep(0.25)


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


show("server/discover", call("server/discover", {}, rid=1))
show("tools/list", call("tools/list", {}, rid=2))
show("tools/call echo", call("tools/call", {"name": "echo", "arguments": {"text": "hi"}}, name="echo", rid=3))
show("tools/call boom (ToolError)", call("tools/call", {"name": "boom", "arguments": {}}, name="boom", rid=4))
show("tools/call boom_async (plain exc)", call("tools/call", {"name": "boom_async", "arguments": {}}, name="boom_async", rid=5))
show("tools/call bad args", call("tools/call", {"name": "echo", "arguments": {}}, name="echo", rid=6))
