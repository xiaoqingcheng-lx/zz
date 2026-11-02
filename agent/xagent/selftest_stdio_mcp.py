# -*- coding: utf-8 -*-
"""stdio 传输 + AnythingLLM MCP Server 自测。

覆盖：
- StdioMcpClient 握手/列工具/调用/错误/超时/子进程退出
- McpRegistry 读取 type=stdio 配置并注册工具
- 真实的 AnythingLLM MCP Server（4 个工具、能列出工作区）

用法：python selftest_stdio_mcp.py
"""
import json
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_client import McpError, McpRegistry, StdioMcpClient  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


# ---------------- mock stdio MCP server ----------------
MOCK = textwrap.dedent(r'''
import json, sys, time

def reply(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        reply({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock", "version": "0.1"}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        reply({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "echo", "description": "回显", "inputSchema": {
                "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
            {"name": "boom", "description": "总是报错", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "slow", "description": "很慢", "inputSchema": {"type": "object", "properties": {}}},
        ]}})
    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments") or {}
        if name == "echo":
            reply({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": args.get("text", "")}], "isError": False}})
        elif name == "boom":
            reply({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": "故意失败"}})
        elif name == "slow":
            time.sleep(30)
    else:
        reply({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method"}})
''')

mock_path = Path(tempfile.gettempdir()) / "_mock_stdio_mcp.py"
mock_path.write_text(MOCK, encoding="utf-8")

print("① StdioMcpClient 基本流程")
client = StdioMcpClient("Mock", sys.executable, [str(mock_path)], timeout=10)
info = client.connect()
check("initialize 返回 serverInfo", info.get("name") == "mock", str(info))
tools = client.list_tools()
check("tools/list 拿到 3 个工具", [t["name"] for t in tools] == ["echo", "boom", "slow"], str([t["name"] for t in tools]))

print("② 工具调用")
r = client.call_tool("echo", {"text": "你好"})
check("echo 返回文本", r["content"][0]["text"] == "你好", str(r)[:80])
try:
    client.call_tool("boom", {})
    check("服务端 error 抛出 McpError", False, "没有抛异常")
except McpError as e:
    check("服务端 error 抛出 McpError", "故意失败" in str(e), str(e)[:60])

print("③ 注册表以 stdio 方式加载")
reg = McpRegistry()
reg.load({"mcpServers": {"Mock": {"type": "stdio", "command": sys.executable,
                                  "args": [str(mock_path)], "timeout": 10}}})
check("服务器计入 clients", "Mock" in reg.clients, str(list(reg.clients)))
check("3 个工具注册成功", reg.server_tools.get("Mock") == 3, str(reg.server_tools))
check("工具名可被 owns 识别", reg.owns("echo"), str(list(reg.tools)))
out = json.loads(reg.call("echo", {"text": "hi"}))
check("通过注册表调用成功", out.get("text") == "hi", str(out)[:80])
check("调用结果带服务器名", out.get("server") == "Mock", str(out)[:60])
out = json.loads(reg.call("boom", {}))
check("工具级错误返回 error 字段", "error" in out, str(out)[:100])

print("④ 异常与边界")
reg2 = McpRegistry()
reg2.load({"mcpServers": {"Bad": {"type": "stdio", "command": "C:/no/such/exe.exe"}}})
check("启动失败只记录原因", "Bad" in reg2.failures and "无法启动" in reg2.failures["Bad"],
      reg2.failures.get("Bad", "")[:60])
reg3 = McpRegistry()
reg3.load({"mcpServers": {"NoCmd": {"type": "stdio"}}})
check("缺 command 被拒绝", "缺少 command" in reg3.failures.get("NoCmd", ""), str(reg3.failures))
slow = StdioMcpClient("Slow", sys.executable, [str(mock_path)], timeout=2)
slow.connect()
try:
    slow.call_tool("slow", {})
    check("超时抛 McpError", False, "没有超时")
except McpError as e:
    check("超时抛 McpError", "超时" in str(e), str(e)[:60])
slow.close()
check("close 后进程已结束", slow.proc.poll() is not None, str(slow.proc.poll()))

print("⑤ 真实 AnythingLLM MCP Server")
venv_py = r"D:\大语言模型\pethospitalMCP\.venv-mcp\Scripts\python.exe"
srv = r"D:\大语言模型\AnythingLLMMCP\anythingllm_mcp_server.py"
if not Path(venv_py).is_file() or not Path(srv).is_file():
    check("文件存在", False, f"{venv_py} / {srv}")
else:
    reg4 = McpRegistry()
    reg4.load({"mcpServers": {"AnythingLLM": {
        "type": "stdio", "command": venv_py, "args": [srv],
        "env": {"ANYTHINGLLM_BASE_URL": "http://127.0.0.1:3001/api/v1"}, "timeout": 60}}})
    check("连接成功", "AnythingLLM" in reg4.clients, str(reg4.failures))
    names = [t.name for t in reg4.tools.values()]
    check("注册 4 个 anythingllm_* 工具", len(names) == 4 and all(n.startswith("anythingllm_") for n in names),
          str(names))
    check("工具名不与本地工具冲突", not (set(names) & {"RunCli", "fetchWeb", "loadSkill", "officeCli"}), str(names))
    out = json.loads(reg4.call("anythingllm_list_workspaces", {}))
    text = out.get("text", "")
    check("list_workspaces 返回 JSON 结果", '"workspaces"' in text, text[:120])
    check("能读到「我的工作区」", "我的工作区" in text, text[:120])
    out = json.loads(reg4.call("anythingllm_vector_search", {"workspace": "不存在的区", "query": "x"}))
    check("不存在的工作区返回可选列表", "未找到工作区" in out.get("text", ""), out.get("text", "")[:100])

for c in list(reg.clients.values()) + list(reg2.clients.values()) + list(reg3.clients.values()):
    try:
        c.close()
    except Exception:  # noqa: BLE001
        pass
client.close()

print()
print(f"通过 {passed} 项，失败 {failed} 项")
sys.exit(0 if failed == 0 else 1)
