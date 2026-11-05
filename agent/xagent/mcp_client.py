# -*- coding: utf-8 -*-
"""MCP 客户端：把远程 MCP Server 的工具接进 xAgent 的 Function Calling 流程。

对应实验要求：
1. **发现与注册**：连接后在 ``initialize`` 之后调用 ``tools/list`` 拿名称/描述/参数 Schema，
   动态注册到 xAgent 的工具集合，LLM 用起来和本地工具（RunCli/loadSkill/officeCli）没有区别；
2. **名称冲突**：内部维护「暴露给 LLM 的工具名 → (服务器, 原始工具名)」映射；
   跨服务器重名或与本地工具重名时，自动加 ``服务器名__工具名`` 前缀；
3. **调用**：按映射找到对应服务器，用 JSON-RPC 转发 ``tools/call``，
   把文本内容 / 结构化数据 / 错误信息整理成 role=tool 消息回给 LLM；
4. **容错**：某个 Server 连不上只记录失败原因，绝不影响其它 Server 与本地工具。

传输方式：Streamable HTTP（POST JSON-RPC，响应可能是 JSON 或 SSE 流）。
只用标准库，不引入第三方依赖。
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# 连接/单次调用超时（秒）
CONNECT_TIMEOUT = 8
CALL_TIMEOUT = 30
# 依次尝试的协议版本：服务端会回它自己支持的版本
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05", "2026-07-28")
MAX_LIST_PAGES = 20

# 本地已有工具名，MCP 工具撞上就加前缀
RESERVED_NAMES = {"RunCli", "fetchWeb", "loadSkill", "createSkill", "fileOps", "officeCli", "recallContext"}


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "-", text).strip("-").lower() or "mcp"


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class McpError(RuntimeError):
    """MCP 调用失败（网络、协议或服务端返回的 error）。"""


@dataclass
class McpTool:
    server: str
    name: str                                   # 服务端原始工具名
    exposed: str                                # 暴露给 LLM 的名字
    description: str
    schema: dict

    def as_schema(self) -> dict:
        params = self.schema or {"type": "object", "properties": {}}
        params = dict(params)
        params.setdefault("type", "object")
        return {
            "type": "function",
            "function": {
                "name": self.exposed,
                "description": (self.description or f"MCP 工具 {self.name}").strip()[:1024],
                "parameters": params,
            },
        }


@dataclass
class McpClient:
    """一个 MCP Server 的 Streamable HTTP 客户端。"""

    name: str
    url: str
    timeout: float = CALL_TIMEOUT
    connect_timeout: float = CONNECT_TIMEOUT
    protocol: str = PROTOCOL_VERSIONS[0]
    session_id: str | None = None
    capabilities: dict = field(default_factory=dict)
    _opener_cache: object = field(default=None, repr=False, compare=False)

    # ---------------- 底层 JSON-RPC ----------------
    def _opener(self):
        """回环地址绕过系统代理（本机 MCP 走代理会被 502），外部地址走环境代理。"""
        if self._opener_cache is not None:
            return self._opener_cache
        host = (urllib.parse.urlsplit(self.url).hostname or "").lower()
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            self._opener_cache = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        else:
            self._opener_cache = urllib.request.build_opener()
        return self._opener_cache

    def _post(self, payload: dict, timeout: float | None = None) -> dict | None:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol,
            "User-Agent": "xAgent-MCP-Client/1.0",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        opener = self._opener()
        try:
            with opener.open(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                ctype = (resp.headers.get("Content-Type") or "").lower()
                status = resp.status
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            raise McpError(f"HTTP {e.code}：{body or e.reason}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise McpError(f"连接失败：{getattr(e, 'reason', e)}") from None

        if status == 202 or not raw.strip():
            return None
        if "text/event-stream" in ctype:
            return self._parse_sse(raw, payload.get("id"))
        try:
            return json.loads(raw)
        except ValueError:
            raise McpError(f"响应不是合法 JSON：{raw[:200]}") from None

    @staticmethod
    def _parse_sse(raw: str, want_id) -> dict | None:
        """从 SSE 流里取出 id 匹配（或最后一个）的 JSON-RPC 响应。"""
        events: list[dict] = []
        buf: list[str] = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                buf.append(line[5:].lstrip())
            elif not line.strip() and buf:
                chunk = "\n".join(buf)
                buf = []
                try:
                    events.append(json.loads(chunk))
                except ValueError:
                    continue
        if buf:
            try:
                events.append(json.loads("\n".join(buf)))
            except ValueError:
                pass
        for ev in events:
            if want_id is not None and ev.get("id") == want_id:
                return ev
        return events[-1] if events else None

    def _rpc(self, method: str, params: dict | None = None, notify: bool = False,
             timeout: float | None = None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            payload["id"] = 1
        resp = self._post(payload, timeout=timeout)
        if notify:
            return None
        if resp is None:
            raise McpError(f"{method} 无响应")
        if "error" in resp:
            err = resp["error"] or {}
            raise McpError(f"{err.get('message') or err}")
        return resp.get("result")

    # ---------------- 协议流程 ----------------
    def connect(self) -> dict:
        """initialize → notifications/initialized，返回 serverInfo。"""
        last: Exception | None = None
        for version in PROTOCOL_VERSIONS:
            self.protocol = version
            try:
                result = self._rpc("initialize", {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "xAgent", "version": "1.0"},
                }, timeout=self.connect_timeout)
                self.capabilities = (result or {}).get("capabilities", {})
                self.protocol = (result or {}).get("protocolVersion", version)
                try:
                    self._rpc("notifications/initialized", notify=True,
                              timeout=self.connect_timeout)
                except McpError:
                    pass                      # 无状态服务端可能忽略该通知
                return (result or {}).get("serverInfo", {})
            except McpError as e:
                last = e
        raise McpError(str(last) if last else "initialize 失败")

    def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor = None
        for _ in range(MAX_LIST_PAGES):
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params, timeout=self.connect_timeout) or {}
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool: str, arguments: dict) -> dict:
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments or {}},
                           timeout=self.timeout) or {}
        return result


class StdioMcpClient:
    """通过子进程 stdin/stdout 通信的 MCP 客户端（stdio 传输）。

    用于 AnythingLLM 这类只支持 stdio 的场景，或本地脚本形式的 MCP Server。
    子进程按行收发 JSON-RPC；stderr 单独收集，出错时附在错误信息里方便排查。
    """

    def __init__(self, name: str, command: str, args: list | None = None,
                 env: dict | None = None, timeout: float = CALL_TIMEOUT,
                 cwd: str | None = None, connect_timeout: float = CONNECT_TIMEOUT):
        self.name = name
        self.command = command
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.protocol = PROTOCOL_VERSIONS[0]
        self.capabilities: dict = {}
        self._queue: queue.Queue = queue.Queue()
        self._stderr: list[str] = []
        self._id = 0
        self._closed = False

        child_env = {k: v for k, v in os.environ.items() if k.lower() not in
                     ("http_proxy", "https_proxy", "all_proxy")}    # 子进程默认直连，避免代理拦本机请求
        child_env.update({k: str(v) for k, v in (env or {}).items()})
        child_env.setdefault("PYTHONUNBUFFERED", "1")
        child_env.setdefault("PYTHONIOENCODING", "utf-8")

        try:
            self.proc = subprocess.Popen(
                [command, *[str(a) for a in (args or [])]],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=child_env, cwd=cwd,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            raise McpError(f"无法启动 stdio MCP Server（{command}）：{e}") from None

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        atexit.register(self.close)

    # ---------------- 进程 IO ----------------
    def _read_stdout(self) -> None:
        stream = self.proc.stdout
        if stream is None:
            return
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                self._queue.put(json.loads(line))
            except ValueError:
                continue
        self._queue.put(None)             # EOF 哨兵

    def _read_stderr(self) -> None:
        stream = self.proc.stderr
        if stream is None:
            return
        for line in stream:
            self._stderr.append(line.rstrip())
            if len(self._stderr) > 40:
                self._stderr.pop(0)

    def _stderr_hint(self) -> str:
        tail = " | ".join(self._stderr[-3:])
        return f"（stderr: {tail[:300]}）" if tail else ""

    def _write(self, payload: dict) -> None:
        stdin = self.proc.stdin
        if stdin is None or self.proc.poll() is not None:
            raise McpError(f"stdio Server「{self.name}」已退出{self._stderr_hint()}")
        try:
            stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise McpError(f"写入 stdio Server 失败：{e}{self._stderr_hint()}") from None

    def _read_until(self, want_id, timeout: float):
        import time as _time
        deadline = _time.monotonic() + timeout
        while True:
            remain = deadline - _time.monotonic()
            if remain <= 0:
                raise McpError(f"等待 {want_id} 响应超时（{timeout}s）{self._stderr_hint()}")
            try:
                item = self._queue.get(timeout=remain)
            except queue.Empty:
                raise McpError(f"等待 {want_id} 响应超时（{timeout}s）{self._stderr_hint()}") from None
            if item is None:
                raise McpError(f"stdio Server「{self.name}」提前退出{self._stderr_hint()}")
            if want_id is None:
                continue
            if item.get("id") == want_id:
                return item
            # 其它 id 的响应/通知：暂不排队等，直接忽略（教学场景够用）

    # ---------------- JSON-RPC ----------------
    def _rpc(self, method: str, params: dict | None = None, notify: bool = False,
             timeout: float | None = None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if notify:
            self._write(payload)
            return None
        self._id += 1
        payload["id"] = self._id
        self._write(payload)
        resp = self._read_until(self._id, timeout or self.timeout)
        if "error" in resp:
            err = resp["error"] or {}
            raise McpError(f"{err.get('message') or err}")
        return resp.get("result")

    # ---------------- 协议流程（与 HTTP 客户端一致） ----------------
    def connect(self) -> dict:
        last: Exception | None = None
        for version in PROTOCOL_VERSIONS:
            self.protocol = version
            try:
                result = self._rpc("initialize", {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "xAgent", "version": "1.0"},
                }, timeout=self.connect_timeout)
                self.capabilities = (result or {}).get("capabilities", {})
                self.protocol = (result or {}).get("protocolVersion", version)
                self._rpc("notifications/initialized", notify=True)
                return (result or {}).get("serverInfo", {})
            except McpError as e:
                last = e
        raise McpError(str(last) if last else "initialize 失败")

    def list_tools(self) -> list[dict]:
        result = self._rpc("tools/list", {}, timeout=self.connect_timeout) or {}
        return result.get("tools") or []

    def call_tool(self, tool: str, arguments: dict) -> dict:
        return self._rpc("tools/call", {"name": tool, "arguments": arguments or {}},
                         timeout=self.timeout) or {}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except OSError:
            pass


class McpRegistry:
    """所有 MCP Server 的集合：负责加载配置、连接、注册工具、分发调用。"""

    def __init__(self, config_path: Path | None = None,
                 connect_timeout: float = CONNECT_TIMEOUT,
                 call_timeout: float = CALL_TIMEOUT):
        self.config_path = config_path
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.clients: dict[str, McpClient] = {}
        self.tools: dict[str, McpTool] = {}          # exposed -> McpTool
        self.failures: dict[str, str] = {}           # server -> 失败原因
        self.server_tools: dict[str, int] = {}       # server -> 工具数
        self.loaded = False                          # 是否已执行过一次加载

    # ---------------- 加载与连接 ----------------
    def load(self, config: dict) -> None:
        """连接全部服务器并注册工具。

        全程先在局部变量里构建（new_clients / new_failures / new_server_tools /
        new_tools），最后一次性赋值回实例——异步加载时，其它线程正在
        遍历这些字典也不会遇到「迭代中变更」。
        """
        servers = (config or {}).get("mcpServers") or config or {}
        if not isinstance(servers, dict):
            raise McpError("配置格式错误：mcpServers 必须是对象")
        new_failures: dict[str, str] = dict(self.failures)
        new_clients: dict = dict(self.clients)
        new_server_tools: dict[str, int] = dict(self.server_tools)
        raw: list[tuple[str, object, list[dict]]] = []
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                new_failures[name] = "配置项不是对象"
                continue
            ctype = (cfg.get("type") or ("stdio" if cfg.get("command") else "streamable_http")).lower()
            if ctype in ("stdio", "child_process", "child-process"):
                command = cfg.get("command") or ""
                if not command:
                    new_failures[name] = "stdio 服务器缺少 command"
                    continue
                try:
                    client = StdioMcpClient(
                        name=name,
                        command=command,
                        args=list(cfg.get("args") or []),
                        env=dict(cfg.get("env") or {}),
                        timeout=float(cfg.get("timeout") or self.call_timeout),
                        connect_timeout=float(cfg.get("connect_timeout") or self.connect_timeout),
                    )
                    client.connect()
                    listed = client.list_tools()
                except McpError as e:
                    new_failures[name] = str(e)
                    continue
                new_clients[name] = client          # type: ignore[assignment]
                raw.append((name, client, listed))
                new_server_tools[name] = len(listed)
                continue

            url = cfg.get("url") or ""
            if ctype not in ("streamable_http", "http", "streamable-http", "streamable"):
                new_failures[name] = f"暂不支持的传输类型 {ctype}（支持 streamable_http / stdio）"
                continue
            if not url:
                new_failures[name] = "缺少 url"
                continue
            client = McpClient(name=name, url=url,
                               timeout=float(cfg.get("timeout") or self.call_timeout),
                               connect_timeout=float(cfg.get("connect_timeout") or self.connect_timeout))
            try:
                client.connect()
                listed = client.list_tools()
            except McpError as e:
                new_failures[name] = str(e)
                continue
            new_clients[name] = client
            raw.append((name, client, listed))
            new_server_tools[name] = len(listed)
        self.clients = new_clients
        self.failures = new_failures
        self.server_tools = new_server_tools

        # 先统计重名，决定是否加服务器前缀（本地构建，最后一次性赋值，
        # 这样异步加载时其它线程遍历 self.tools 不会遇到迭代中变更）
        counts: dict[str, int] = {}
        for _name, _client, listed in raw:
            for t in listed:
                counts[t.get("name", "")] = counts.get(t.get("name", ""), 0) + 1
        new_tools: dict[str, McpTool] = {}
        for name, _client, listed in raw:
            for t in listed:
                tool_name = t.get("name", "")
                if not tool_name:
                    continue
                need_prefix = counts.get(tool_name, 0) > 1 or tool_name in RESERVED_NAMES
                exposed = f"{_slug(name)}__{tool_name}" if need_prefix else tool_name
                if exposed in new_tools:       # 极端情况：仍然撞名，强制前缀
                    exposed = f"{_slug(name)}__{tool_name}"
                new_tools[exposed] = McpTool(
                    server=name,
                    name=tool_name,
                    exposed=exposed,
                    description=t.get("description") or "",
                    schema=t.get("inputSchema") or {},
                )
        self.tools = new_tools
        self.loaded = True

    # ---------------- 配置文件加载（可延迟 / 异步调用） ----------------
    def load_file(self, path: str | Path | None = None) -> "McpRegistry":
        """从 .mcp.json 读取并连接全部服务器；文件缺失静默返回。"""
        path = Path(path or self.config_path or "")
        self.config_path = path
        if not str(path) or not path.is_file():
            self.loaded = True
            return self
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.failures["<配置文件>"] = f"读取失败：{e}"
            self.loaded = True
            return self
        self.load(config)
        return self

    @classmethod
    def from_file(cls, path: str | Path | None = None,
                  connect_timeout: float = CONNECT_TIMEOUT,
                  call_timeout: float = CALL_TIMEOUT) -> "McpRegistry":
        reg = cls(Path(path) if path else None,
                  connect_timeout=connect_timeout, call_timeout=call_timeout)
        return reg.load_file(path)

    # ---------------- 对外接口 ----------------
    def schemas(self) -> list[dict]:
        return [t.as_schema() for t in self.tools.values()]

    def owns(self, name: str) -> bool:
        return name in self.tools

    def call(self, exposed: str, arguments: dict) -> str:
        tool = self.tools.get(exposed)
        if tool is None:
            return _dump({"error": f"未知 MCP 工具：{exposed}"})
        client = self.clients.get(tool.server)
        if client is None:
            return _dump({
                "error": f"服务器「{tool.server}」当前不可用",
                "reason": self.failures.get(tool.server, "未连接"),
            })
        try:
            result = client.call_tool(tool.name, arguments)
        except McpError as e:
            return _dump({
                "error": f"调用 {tool.server}/{tool.name} 失败",
                "reason": str(e),
                "server": tool.server,
                "tool": tool.name,
            })
        return _dump(self._shape_result(tool, result))

    @staticmethod
    def _shape_result(tool: McpTool, result: dict) -> dict:
        """把 MCP 的 content 数组整理成 LLM 好读的结构。"""
        texts: list[str] = []
        others: list[dict] = []
        for item in result.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                texts.append(item.get("text") or "")
            else:
                others.append({"type": item.get("type"), **{
                    k: v for k, v in item.items() if k != "type"
                }})
        payload: dict = {
            "server": tool.server,
            "tool": tool.name,
            "text": "\n".join(t for t in texts if t).strip(),
        }
        if result.get("structuredContent") is not None:
            payload["structured"] = result["structuredContent"]
        if others:
            payload["other"] = others
        if result.get("isError"):
            payload["is_error"] = True
        return payload

    # ---------------- 概览 ----------------
    def summary(self) -> str:
        total = len(self.clients)
        if not total and not self.failures:
            return "MCP：未配置（.mcp.json 不存在或为空）"
        lines = [f"MCP：已连接 {total} 个服务器，注册 {len(self.tools)} 个工具"]
        for name, cnt in self.server_tools.items():
            lines.append(f"  ✓ {name}：{cnt} 个工具")
        for name, reason in self.failures.items():
            lines.append(f"  ✗ {name}：{reason[:80]}")
        return "\n".join(lines)

    def prompt_section(self) -> str:
        """注入 System Prompt 的 MCP 概览（只列工具名与一句话说明）。"""
        if not self.tools:
            return ""
        lines = ["", "以下是 MCP 服务器提供的远程工具（调用方式与本地工具完全相同）："]
        for t in self.tools.values():
            desc = re.sub(r"\s+", " ", t.description).strip()[:70]
            lines.append(f"- `{t.exposed}`（{t.server}）：{desc}")
        return "\n".join(lines)
