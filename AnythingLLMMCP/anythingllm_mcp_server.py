# -*- coding: utf-8 -*-
"""AnythingLLM MCP Server（stdio）—— 把 AnythingLLM 的知识库能力暴露成 MCP 工具。

为什么需要它：AnythingLLM 本身只提供 REST API（默认 http://localhost:3001/api/v1），
不是 MCP Server；而 xAgent / AnythingLLM 桌面版这类 MCP 客户端需要标准协议。
本文件用官方 Python SDK（mcp 2.x）包一层 stdio MCP Server，工具内转发到 REST API。

提供的工具（只做 AnythingLLM 独有的能力，不与宠物医院 / 八字等既有 MCP 工具重复）：
- anythingllm_list_workspaces  列出所有工作区
- anythingllm_vector_search    在工作区知识库里做语义检索
- anythingllm_chat             向工作区提问（RAG 回答）
- anythingllm_upload_text      把一段文本作为文档上传，并可加入指定工作区

API Key 解析顺序：环境变量 ANYTHINGLLM_API_KEY → apikey.local.txt → index.html 里的常量。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from mcp.server import MCPServer

BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "http://127.0.0.1:3001/api/v1").rstrip("/")
TIMEOUT = float(os.environ.get("ANYTHINGLLM_TIMEOUT", "60"))

_ROOT = Path(__file__).resolve().parent
_UP = _ROOT.parent
_KEY_CANDIDATES = [
    _ROOT / "anythingllm-upload" / "apikey.local.txt",
    _UP / "AnythingLLMServer" / "anythingllm-upload" / "apikey.local.txt",
    _ROOT / "apikey.local.txt",
    _ROOT / "anythingllm-upload" / "index.html",
    _UP / "AnythingLLMServer" / "anythingllm-upload" / "index.html",
]
_KEY_PATTERN = re.compile(r"[A-Z0-9]{7}-[A-Z0-9]{7}-[A-Z0-9]{7}-[A-Z0-9]{7}")


def resolve_api_key() -> str:
    """找到 API Key：环境变量优先，其次本地备份文件，最后 index.html 常量。"""
    env = (os.environ.get("ANYTHINGLLM_API_KEY") or "").strip()
    if env:
        return env
    for path in _KEY_CANDIDATES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _KEY_PATTERN.search(text)
        if m:
            return m.group(0)
    return ""


def _opener():
    """回环地址绕过系统代理（代理会把本机请求拦成 502）。"""
    host = (urllib.parse.urlsplit(BASE_URL).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _request(method: str, path: str, payload: dict | None = None,
             raw: bytes | None = None, content_type: str | None = None) -> dict:
    key = resolve_api_key()
    if not key:
        return {"error": "未找到 AnythingLLM API Key",
                "hint": "设置环境变量 ANYTHINGLLM_API_KEY，或确认 anythingllm-upload/apikey.local.txt 存在"}
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        data = raw
        headers["Content-Type"] = content_type or "application/octet-stream"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _opener().open(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(500).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return {"error": f"HTTP {e.code} {e.reason}", "detail": body[:400]}
    except urllib.error.URLError as e:
        return {"error": f"连接失败：{e.reason}",
                "hint": "确认 AnythingLLM 桌面版已启动（默认 3001 端口）"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def _workspaces() -> list[dict]:
    data = _request("GET", "/workspaces")
    return data.get("workspaces") or [] if isinstance(data, dict) else []


def _resolve_workspace(name_or_slug: str) -> dict | None:
    """按 slug / 名称（不区分大小写）找到工作区。"""
    target = (name_or_slug or "").strip().lower()
    for ws in _workspaces():
        if target in (str(ws.get("slug", "")).lower(), str(ws.get("name", "")).lower()):
            return ws
    return None


server = MCPServer(
    name="anythingllm-mcp",
    version="1.0.0",
    instructions=(
        "AnythingLLM 知识库工具：可列出工作区、语义检索已上传文档、"
        "基于知识库问答、上传文本作为新文档。"
        "涉及用户私有知识库内容时优先用这些工具，不要凭空回答。"
    ),
)


@server.tool(name="anythingllm_list_workspaces", description="列出 AnythingLLM 的所有工作区（名称与 slug）")
async def list_workspaces() -> str:
    """列出工作区。"""
    data = _request("GET", "/workspaces")
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)
    items = [{"name": w.get("name"), "slug": w.get("slug"),
              "documents": len((w.get("documents") or []))} for w in data.get("workspaces") or []]
    return json.dumps({"count": len(items), "workspaces": items}, ensure_ascii=False)


@server.tool(name="anythingllm_vector_search",
             description="在指定工作区的知识库里做语义检索，返回最相关的文档片段")
async def vector_search(workspace: str, query: str, topN: int = 4) -> str:
    """在工作区知识库中检索。

    Args:
        workspace: 工作区名称或 slug
        query: 检索问题
        topN: 返回片段数，1-10，默认 4
    """
    ws = _resolve_workspace(workspace)
    if ws is None:
        return json.dumps({"error": f"未找到工作区：{workspace}",
                           "available": [w.get("name") for w in _workspaces()]}, ensure_ascii=False)
    n = max(1, min(int(topN or 4), 10))
    data = _request("POST", f"/workspace/{ws['slug']}/vector-search",
                    {"query": query, "topN": n, "scoreThreshold": 0.2})
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)
    results = [{"score": round(r.get("score", 0), 4),
                "text": (r.get("text") or "")[:1200],
                "source": (r.get("metadata") or {}).get("title") or (r.get("metadata") or {}).get("url")}
               for r in data.get("results") or []]
    return json.dumps({"workspace": ws.get("name"), "query": query,
                       "count": len(results), "results": results}, ensure_ascii=False)


@server.tool(name="anythingllm_chat",
             description="向指定工作区提问，AnythingLLM 会基于该工作区知识库检索后回答（RAG）")
async def chat(workspace: str, message: str, mode: str = "chat") -> str:
    """向工作区提问。

    Args:
        workspace: 工作区名称或 slug
        message: 用户问题
        mode: 回答模式，chat（对话）或 query（仅检索不记忆），默认 chat
    """
    ws = _resolve_workspace(workspace)
    if ws is None:
        return json.dumps({"error": f"未找到工作区：{workspace}",
                           "available": [w.get("name") for w in _workspaces()]}, ensure_ascii=False)
    data = _request("POST", f"/workspace/{ws['slug']}/chat",
                    {"message": message, "mode": "query" if mode == "query" else "chat"})
    if "error" in data:
        return json.dumps(data, ensure_ascii=False)
    sources = [s.get("title") or s.get("url") for s in (data.get("sources") or [])]
    return json.dumps({"workspace": ws.get("name"), "answer": data.get("textResponse", ""),
                       "sources": [s for s in sources if s]}, ensure_ascii=False)


@server.tool(name="anythingllm_upload_text",
             description="把一段文本保存为文档并上传到 AnythingLLM，可选加入指定工作区（随后可被检索）")
async def upload_text(title: str, text: str, workspace: str = "") -> str:
    """上传文本为文档。

    Args:
        title: 文档标题（用作文件名）
        text: 文档正文
        workspace: 要加入的工作区名称或 slug，留空则只上传不加入
    """
    safe_title = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", title or "document")[:60] or "document"
    tmp_path = Path(tempfile.gettempdir()) / f"{safe_title}_{uuid.uuid4().hex[:6]}.txt"
    try:
        tmp_path.write_text(text, encoding="utf-8")
        boundary = f"----xAgentBoundary{uuid.uuid4().hex}"
        content = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{tmp_path.name}"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode() + tmp_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        data = _request("POST", "/document/upload", raw=content,
                        content_type=f"multipart/form-data; boundary={boundary}")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    if "error" in data:
        return json.dumps(data, ensure_ascii=False)
    docs = data.get("documents") or []
    locations = [d.get("location") for d in docs if d.get("location")]
    added = None
    if workspace:
        ws = _resolve_workspace(workspace)
        if ws is None:
            return json.dumps({"uploaded": locations, "warning": f"文档已上传，但未找到工作区：{workspace}"},
                              ensure_ascii=False)
        res = _request("POST", f"/workspace/{ws['slug']}/update-embeddings", {"adds": locations})
        added = {"workspace": ws.get("name"), "ok": "error" not in res,
                 "detail": res.get("error") if "error" in res else None}
    return json.dumps({"uploaded": locations, "added_to_workspace": added}, ensure_ascii=False)


def main() -> None:
    import anyio
    anyio.run(server.run_stdio_async)


if __name__ == "__main__":
    main()
