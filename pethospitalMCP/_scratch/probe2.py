"""Probe proto2: schema shapes, middleware normalisation, SDK client over HTTP."""

import json
import time

import httpx

BASE = "http://127.0.0.1:8902"
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

r = call("tools/list", {}, rid=1).json()
print("===== tools/list schemas =====")
for t in r["result"]["tools"]:
    print("\n---", t["name"], "---")
    print("description:", t.get("description"))
    print("inputSchema:", json.dumps(t["inputSchema"], ensure_ascii=False))
    print("outputSchema:", json.dumps(t.get("outputSchema"), ensure_ascii=False))

print("\n\n===== error normalisation =====")
print("-- model_param with unknown field --")
print(json.dumps(call("tools/call", {"name": "model_param", "arguments": {"filters": {"species": "犬", "bogus": 1}}}, name="model_param", rid=2).json(), ensure_ascii=False, indent=2))
print("-- model_param with bad type --")
print(json.dumps(call("tools/call", {"name": "model_param", "arguments": {"filters": {"page": "abc"}}}, name="model_param", rid=3).json(), ensure_ascii=False, indent=2))
print("-- flat_params with bad enum --")
print(json.dumps(call("tools/call", {"name": "flat_params", "arguments": {"species": "恐龙"}}, name="flat_params", rid=4).json(), ensure_ascii=False, indent=2))
print("-- flat_params pageSize out of range --")
print(json.dumps(call("tools/call", {"name": "flat_params", "arguments": {"pageSize": 9999}}, name="flat_params", rid=5).json(), ensure_ascii=False, indent=2))
print("-- raises_tool_error --")
print(json.dumps(call("tools/call", {"name": "raises_tool_error", "arguments": {}}, name="raises_tool_error", rid=6).json(), ensure_ascii=False, indent=2))
print("-- good model_param call (structuredContent) --")
print(json.dumps(call("tools/call", {"name": "model_param", "arguments": {"filters": {"species": "犬", "page": 2}}}, name="model_param", rid=7).json(), ensure_ascii=False, indent=2))

print("\n\n===== SDK client over HTTP =====")
from mcp import Client  # noqa: E402


async def main():
    async with Client(MCP) as client:
        print("protocol_version:", client.protocol_version)
        print("server_info:", client.server_info)
        tools = await client.list_tools()
        print("client list_tools ->", [t.name for t in tools.tools])
        for name, args in [
            ("flat_params", {"species": "犬", "page": 2}),
            ("flat_params", {"species": "恐龙"}),
            ("model_param", {"filters": {"species": "犬"}}),
        ]:
            res = await client.call_tool(name, args)
            print(f"  call {name} {args} -> is_error={res.is_error} structured={res.structured_content} content={[b.text[:120] for b in res.content]}")


import anyio  # noqa: E402

anyio.run(main)
