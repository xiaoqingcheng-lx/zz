# -*- coding: utf-8 -*-
"""fetchWeb —— xAgent 的 Function Calling 工具：抓取一个网页并返回可读文本。

设计要点：
1. 只接受 http/https，避免 file:// 等本地协议被滥用；
2. 自动识别 Content-Type：HTML 会去掉 script/style/标签、反转义实体、压空白，
   JSON/纯文本原样返回；
3. 带超时（默认 20s）与重定向跟随，失败返回结构化错误而不是抛异常；
4. 过长内容按 MAX_CHARS 截断并**标明截断**，避免撑爆上下文；
5. 本机回环地址绕过系统代理（代理会拦截 127.0.0.1），外部地址沿用环境代理。
"""
import html
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 20         # 单次抓取超时（秒）
MAX_CHARS = 6000     # 返回正文最大字符数
MAX_BYTES = 3_000_000  # 最多读取 3MB，防止下载大文件
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) xAgent/1.0"

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetchWeb",
        "description": (
            "抓取网页内容并返回可读文本。url 必须是 http:// 或 https:// 开头的完整地址。"
            "HTML 页面会被转成纯文本（去掉脚本、样式和标签）；"
            "查询最新信息、读取在线文档时使用它，不要凭空编造网页内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的完整网页地址，例如 https://example.com",
                },
                "maxChars": {
                    "type": "integer",
                    "description": "返回正文的最大字符数，默认 6000，超过会截断",
                },
            },
            "required": ["url"],
        },
    },
}


def _is_loopback(host: str) -> bool:
    host = (host or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")


def _build_opener(url: str, insecure: bool = False):
    """回环地址不走代理，其它地址用环境代理（urllib 默认行为）。

    insecure=True 时不校验证书（仅在默认校验因中间人代理失败后作为降级手段）。
    """
    host = urllib.parse.urlparse(url).hostname or ""
    handlers = []
    if _is_loopback(host):
        handlers.append(urllib.request.ProxyHandler({}))
    if insecure:
        ctx = ssl._create_unverified_context()   # noqa: S323  降级路径，结果里会标注
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def html_to_text(raw: str) -> str:
    """把 HTML 粗加工成可读文本（够 LLM 用，不追求完美渲染）。"""
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def execute_tool(arguments: dict) -> str:
    """执行抓取，返回 JSON 字符串作为 role=tool 消息。"""
    url = (arguments.get("url") or "").strip()
    if not url:
        return _dump({"error": "缺少 url 参数", "hint": "传入完整地址，如 https://example.com"})

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return _dump({"error": f"不支持的协议：{parsed.scheme or '(空)'}",
                      "hint": "只能抓取 http:// 或 https:// 地址"})
    if not parsed.hostname:
        return _dump({"error": "地址缺少主机名", "url": url})

    try:
        limit = int(arguments.get("maxChars") or MAX_CHARS)
    except (TypeError, ValueError):
        limit = MAX_CHARS
    limit = max(200, min(limit, 30000))

    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    tls_verified = True
    try:
        try:
            resp_ctx = _build_opener(url).open(req, timeout=TIMEOUT)
        except urllib.error.URLError as e:
            # 中间人代理（公司/校园网）根证书不在信任链时降级；可用 XAGENT_TLS_STRICT=1 禁止
            if "CERTIFICATE_VERIFY_FAILED" not in str(e) or os.environ.get("XAGENT_TLS_STRICT") == "1":
                raise
            tls_verified = False
            resp_ctx = _build_opener(url, insecure=True).open(req, timeout=TIMEOUT)
        with resp_ctx as resp:
            status = resp.status
            ctype = (resp.headers.get("Content-Type") or "").lower()
            charset = resp.headers.get_content_charset() or "utf-8"
            blob = resp.read(MAX_BYTES)
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(600).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return _dump({"error": f"HTTP {e.code} {e.reason}", "url": url,
                      "hint": "4xx 检查地址是否正确；5xx 稍后重试", "body": body})
    except urllib.error.URLError as e:
        return _dump({"error": f"连接失败：{e.reason}", "url": url,
                      "hint": "确认网络/代理可用，地址拼写正确"})
    except Exception as e:  # noqa: BLE001  超时等
        return _dump({"error": f"{type(e).__name__}: {e}", "url": url,
                      "hint": "超时可缩短目标页面或稍后重试"})

    try:
        raw = blob.decode(charset, "replace")
    except LookupError:
        raw = blob.decode("utf-8", "replace")

    if "html" in ctype or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        text = html_to_text(raw)
    else:
        text = raw.strip()

    truncated = len(text) > limit
    if truncated:
        text = text[:limit]

    payload = {
        "url": final_url,
        "status": status,
        "content_type": ctype or "unknown",
        "chars": len(text),
        "truncated": truncated,
        "text": text,
    }
    if not tls_verified:
        payload["tls_verified"] = False
        payload["notice_tls"] = (
            "HTTPS 证书校验失败（当前网络存在中间人代理），已降级抓取。"
            "如需严格校验，请把代理根证书加入系统信任链。"
        )
    if truncated:
        payload["notice"] = f"内容过长已截断，只返回前 {limit} 字符（原文 {len(raw)} 字符）"
    return _dump(payload)


def _dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)
