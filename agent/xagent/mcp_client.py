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

import json
import re
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
RESERVED_NAMES = {"RunCli", "loadSkill", "createSkill", "fileOps", "officeCli"}


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
                }, timeout=CONNECT_TIMEOUT)
                self.capabilities = (result or {}).get("capabilities", {})
                self.protocol = (result or {}).get("protocolVersion", version)
                try:
                    self._rpc("notifications/initialized", notify=True, timeout=CONNECT_TIMEOUT)
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
            result = self._rpc("tools/list", params, timeout=CONNECT_TIMEOUT) or {}
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool: str, arguments: dict) -> dict:
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments or {}},
                           timeout=self.timeout) or {}
        return result


class McpRegistry:
    """所有 MCP Server 的集合：负责加载配置、连接、注册工具、分发调用。"""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path
        self.clients: dict[str, McpClient] = {}
        self.tools: dict[str, McpTool] = {}          # exposed -> McpTool
        self.failures: dict[str, str] = {}           # server -> 失败原因
        self.server_tools: dict[str, int] = {}       # server -> 工具数

    # ---------------- 加载与连接 ----------------
    def load(self, config: dict) -> None:
        servers = (config or {}).get("mcpServers") or config or {}
        if not isinstance(servers, dict):
            raise McpError("配置格式错误：mcpServers 必须是对象")
        raw: list[tuple[str, McpClient, list[dict]]] = []
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                self.failures[name] = "配置项不是对象"
                continue
            ctype = (cfg.get("type") or "streamable_http").lower()
            url = cfg.get("url") or ""
            if ctype not in ("streamable_http", "http", "streamable-http"):
                self.failures[name] = f"暂不支持的传输类型 {ctype}（只支持 streamable_http）"
                continue
            if not url:
                self.failures[name] = "缺少 url"
                continue
            client = McpClient(name=name, url=url,
                               timeout=float(cfg.get("timeout") or CALL_TIMEOUT))
            try:
                client.connect()
                listed = client.list_tools()
            except McpError as e:
                self.failures[name] = str(e)
                continue
            self.clients[name] = client
            raw.append((name, client, listed))
            self.server_tools[name] = len(listed)

        # 先统计重名，决定是否加服务器前缀
        counts: dict[str, int] = {}
        for _name, _client, listed in raw:
            for t in listed:
                counts[t.get("name", "")] = counts.get(t.get("name", ""), 0) + 1
        for name, _client, listed in raw:
            for t in listed:
                tool_name = t.get("name", "")
                if not tool_name:
                    continue
                need_prefix = counts.get(tool_name, 0) > 1 or tool_name in RESERVED_NAMES
                exposed = f"{_slug(name)}__{tool_name}" if need_prefix else tool_name
                if exposed in self.tools:      # 极端情况：仍然撞名，强制前缀
                    exposed = f"{_slug(name)}__{tool_name}"
                self.tools[exposed] = McpTool(
                    server=name,
                    name=tool_name,
                    exposed=exposed,
                    description=t.get("description") or "",
                    schema=t.get("inputSchema") or {},
                )

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "McpRegistry":
        reg = cls(Path(path) if path else None)
        if path is None or not Path(path).is_file():
            return reg
        try:
            config = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            reg.failures["<配置文件>"] = f"读取失败：{e}"
            return reg
        reg.load(config)
        return reg

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
