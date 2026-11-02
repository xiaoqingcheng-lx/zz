# -*- coding: utf-8 -*-
"""MCP 接入自测：用本地 mock MCP Server 验证发现/注册/映射/调用/容错。

不依赖真实服务，也不调 LLM，可离线跑。
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_client import McpRegistry  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(desc: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(desc)
    print(f"[{'PASS' if ok else 'FAIL'}] {desc}" + (f"  · {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------- #
# mock MCP Server：支持 JSON 与 SSE 两种响应，可配置工具与错误行为
# --------------------------------------------------------------------------- #
class MockState:
    def __init__(self, tools: list[dict], mode: str = "json", fail_tools: set[str] | None = None):
        self.tools = tools
        self.mode = mode
        self.fail_tools = fail_tools or set()
        self.calls: list[tuple[str, dict]] = []


class MockHandler(BaseHTTPRequestHandler):
    state: MockState

    def log_message(self, *_args):        # 静音
        pass

    def _send(self, payload: dict | None, status: int = 200) -> None:
        if payload is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.state.mode == "sse":
            body = f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
        else:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(length).decode() or "{}")
        method = req.get("method")
        rid = req.get("id")
        if method == "notifications/initialized":
            self._send(None)
            return
        if method == "initialize":
            self._send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock", "version": "1.0"},
            }})
            return
        if method == "tools/list":
            self._send({"jsonrpc": "2.0", "id": rid, "result": {"tools": self.state.tools}})
            return
        if method == "tools/call":
            name = (req.get("params") or {}).get("name")
            args = (req.get("params") or {}).get("arguments") or {}
            self.state.calls.append((name, args))
            if name in self.state.fail_tools:
                self._send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": f"{name} 执行失败：库存不足"}],
                    "isError": True,
                }})
                return
            self._send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"{name} 收到 {json.dumps(args, ensure_ascii=False)}"}],
                "structuredContent": {"ok": True, "echo": args},
            }})
            return
        self._send({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"未知方法 {method}"}})


def serve(state: MockState) -> tuple[ThreadingHTTPServer, str]:
    handler = type("H", (MockHandler,), {"state": state})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/mcp"


TOOL_PETS = {
    "name": "search",
    "description": "按关键字查宠物",
    "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
}
TOOL_CLASH = {
    "name": "RunCli",
    "description": "居然和本地工具重名",
    "inputSchema": {"type": "object", "properties": {}},
}

# --------------------------------------------------------------------------- #
section("① 单个服务器：发现与注册")
st_a = MockState([TOOL_PETS])
srv_a, url_a = serve(st_a)
reg = McpRegistry()
reg.load({"mcpServers": {"PetsA": {"type": "streamable_http", "url": url_a}}})
check("连接成功", "PetsA" in reg.clients, reg.summary().splitlines()[0])
check("工具数量正确", len(reg.tools) == 1, str(list(reg.tools)))
check("无冲突时保留原始工具名", "search" in reg.tools, str(list(reg.tools)))
check("描述与参数 Schema 完整",
      reg.tools["search"].description == "按关键字查宠物"
      and "q" in (reg.tools["search"].schema.get("properties") or {}), "")
schema = reg.tools["search"].as_schema()["function"]
check("能转成 OpenAI function 声明",
      schema["name"] == "search" and schema["parameters"]["type"] == "object", "")

section("② 调用转发与结果整理")
out = json.loads(reg.call("search", {"q": "旺财"}))
check("调用被转发到服务器", st_a.calls and st_a.calls[0][0] == "search", str(st_a.calls[:1]))
check("参数原样转发", st_a.calls[0][1] == {"q": "旺财"}, str(st_a.calls[0][1]))
check("文本内容回传给 LLM", "旺财" in out.get("text", ""), out.get("text", "")[:40])
check("结构化数据保留", out.get("structured", {}).get("ok") is True, "")
check("标记了来源服务器", out.get("server") == "PetsA", "")

section("③ 名称冲突：跨服务器同名 / 与本地工具同名")
st_b = MockState([TOOL_PETS])
srv_b, url_b = serve(st_b)
st_c = MockState([TOOL_CLASH])
srv_c, url_c = serve(st_c)
reg2 = McpRegistry()
reg2.load({"mcpServers": {
    "PetsA": {"type": "streamable_http", "url": url_a},
    "PetsB": {"type": "streamable_http", "url": url_b},
    "Utils": {"type": "streamable_http", "url": url_c},
}})
names = sorted(reg2.tools)
check("同名工具自动加服务器前缀", "petsa__search" in names and "petsb__search" in names, str(names))
check("与本地工具重名的也加前缀", "utils__RunCli" in names, str(names))
check("映射仍指向原始工具名",
      reg2.tools["petsa__search"].name == "search" and reg2.tools["petsa__search"].server == "PetsA", "")

section("④ 容错：坏配置 / 连不上 / 工具报错")
reg3 = McpRegistry()
reg3.load({"mcpServers": {
    "Good": {"type": "streamable_http", "url": url_a},
    "Down": {"type": "streamable_http", "url": "http://127.0.0.1:1/mcp"},
    "Stdio": {"type": "stdio", "command": "node"},
    "NoUrl": {"type": "streamable_http"},
}})
check("好服务器照常注册", "Good" in reg3.clients and reg3.tools, str(list(reg3.tools)))
check("连不上的服务器被记录原因", "Down" in reg3.failures and reg3.failures["Down"].strip() != "",
      reg3.failures.get("Down", "")[:60])
check("不支持的类型给出明确提示", "stdio" in reg3.failures.get("Stdio", ""),
      reg3.failures.get("Stdio", ""))
check("缺 url 被拒绝", "url" in reg3.failures.get("NoUrl", ""), reg3.failures.get("NoUrl", ""))
check("一个坏服务器不影响好服务器", len(reg3.tools) == 1, str(list(reg3.tools)))

st_err = MockState([{"name": "buy", "description": "买药", "inputSchema": {"type": "object"}}],
                   fail_tools={"buy"})
srv_e, url_e = serve(st_err)
reg4 = McpRegistry()
reg4.load({"mcpServers": {"Shop": {"type": "streamable_http", "url": url_e}}})
out = json.loads(reg4.call("buy", {}))
check("工具级错误被标记", out.get("is_error") is True, out.get("text", "")[:40])
check("工具级错误仍带原始文本", "库存不足" in out.get("text", ""), "")

section("⑤ SSE 响应与边界情况")
st_sse = MockState([TOOL_PETS], mode="sse")
srv_s, url_s = serve(st_sse)
reg5 = McpRegistry()
reg5.load({"mcpServers": {"Sse": {"type": "streamable_http", "url": url_s}}})
check("text/event-stream 响应能解析", "search" in reg5.tools, str(list(reg5.tools)))
check("SSE 下调用同样可用", "旺财" in reg5.call("search", {"q": "旺财"}), "")

check("未知工具名返回明确错误", "error" in json.loads(reg5.call("不存在的工具", {})), "")
check("配置文件不存在时为空表不报错", len(McpRegistry.from_file("Z:/no/such/.mcp.json").tools) == 0, "")

section("⑥ 接入 xAgent：动态工具声明与分发")
import xagent as xa  # noqa: E402

names = [s["function"]["name"] for s in xa.TOOL_SCHEMAS]
check("TOOL_SCHEMAS 含 MCP 工具", len(xa.TOOL_SCHEMAS) == len(xa.LOCAL_SCHEMAS) + len(xa.MCP.tools),
      f"{len(xa.LOCAL_SCHEMAS)} 本地 + {len(xa.MCP.tools)} MCP")
check("MCP 工具已进入工具声明列表", all(n in names for n in xa.MCP.tools), str(names[:6]))
check("本地工具未被挤掉", all(n in names for n in
                            ("RunCli", "loadSkill", "createSkill", "fileOps", "officeCli")), "")
check("System Prompt 含 MCP 清单", "MCP 服务器提供的远程工具" in xa.system_prompt(), "")

if xa.MCP.tools:
    first = next(iter(xa.MCP.tools))
    r = json.loads(xa.dispatch_tool(first, {}))
    check("dispatch_tool 能分发 MCP 工具", r.get("server") and "error" not in r,
          f"{first} → {r.get('server')}")
else:
    check("dispatch_tool 能分发 MCP 工具", False, "当前无 MCP 工具可测（服务未启动？）")

for srv in (srv_a, srv_b, srv_c, srv_e, srv_s):
    srv.shutdown()

print("\n" + "=" * 52)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "、".join(FAIL))
    sys.exit(1)
