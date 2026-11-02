# -*- coding: utf-8 -*-
"""fetchWeb 工具自测（本地 mock HTTP 服务，不依赖外网）。

用法：python selftest_fetchweb.py
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_web_tool import TOOL_SCHEMA, execute_tool, html_to_text  # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


BIG_BODY = "<html><body><p>" + ("内容段落。" * 3000) + "</p></body></html>"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/html":
            body = ("<html><head><title>测试</title><style>p{color:red}</style>"
                    "<script>var x=1;</script></head><body>"
                    "<h1>标题一</h1><p>正文&nbsp;第一段 &amp; 符号</p>"
                    "<ul><li>条目A</li><li>条目B</li></ul></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/json":
            body = json.dumps({"ok": True, "num": 42}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path == "/big":
            body = BIG_BODY.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/missing":
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/html")
            self.end_headers()
            return
        else:
            body = b"?"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = HTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"


def call(url, **kw):
    args = {"url": url}
    args.update(kw)
    return json.loads(execute_tool(args))


print("① 工具声明")
fn = TOOL_SCHEMA["function"]
check("工具名为 fetchWeb", fn["name"] == "fetchWeb", fn["name"])
check("url 是必需参数", fn["parameters"]["required"] == ["url"], str(fn["parameters"]["required"]))
check("maxChars 可选", "maxChars" in fn["parameters"]["properties"], "")

print("② HTML 转文本")
r = call(f"{base}/html")
text = r.get("text", "")
check("状态码 200 且无错误", r.get("status") == 200 and "error" not in r, str(r)[:80])
check("保留正文文字", "标题一" in text and "正文" in text, text[:60])
check("去掉 script 内容", "var x=1" not in text, "")
check("去掉 style 内容", "color:red" not in text, "")
check("去掉标签尖括号", "<" not in text and ">" not in text, text[:60])
check("实体被反转义", "&nbsp;" not in text and "&amp;" not in text or "&" in text, text[:60])
check("列表项各自成行", "条目A" in text and "条目B" in text, "")

print("③ 非 HTML 原样返回")
r = call(f"{base}/json")
check("JSON 内容原样保留", '"ok": true' in r.get("text", "") or '"ok":true' in r.get("text", ""), r.get("text", "")[:60])

print("④ 截断")
r = call(f"{base}/big", maxChars=500)
check("超过上限被截断", r.get("truncated") is True and len(r.get("text", "")) == 500, str(len(r.get("text", ""))))
check("附带截断提示", "截断" in (r.get("notice") or ""), r.get("notice", ""))
r = call(f"{base}/big")
check("默认上限 6000 生效", len(r.get("text", "")) == 6000, str(len(r.get("text", ""))))

print("⑤ 重定向")
r = call(f"{base}/redirect")
check("跟随 302 到目标页", "标题一" in r.get("text", ""), r.get("text", "")[:40])
check("返回最终 URL", r.get("url", "").endswith("/html"), r.get("url", ""))

print("⑥ 错误处理")
r = call(f"{base}/missing")
check("404 返回结构化错误", "error" in r and "404" in r["error"], str(r)[:80])
check("404 附带处理建议", "hint" in r, "")
r = json.loads(execute_tool({"url": ""}))
check("空 url 被拒绝", "error" in r, str(r)[:60])
r = call("file:///C:/Windows/win.ini")
check("非 http(s) 协议被拒绝", "error" in r and "协议" in r["error"], str(r)[:80])
r = call("http://127.0.0.1:1/none")
check("连不上返回明确错误", "error" in r and "连接失败" in r["error"], str(r)[:80])

print("⑦ 回环地址绕过代理")
import os  # noqa: E402
old = {k: os.environ.get(k) for k in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY")}
os.environ["http_proxy"] = os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"   # 故意坏代理
os.environ["all_proxy"] = os.environ["ALL_PROXY"] = "http://127.0.0.1:9"
r = call(f"{base}/html")
check("坏代理下本机地址仍可抓取", r.get("status") == 200, str(r)[:80])
for k, v in old.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

print("⑧ 文本清洗函数独立可用")
check("html_to_text 处理空字符串", html_to_text("") == "", repr(html_to_text("")))
check("html_to_text 折叠多余空行", "\n\n\n" not in html_to_text("<p>a</p><p>b</p>"), "")

srv.shutdown()
print()
print(f"通过 {passed} 项，失败 {failed} 项")
sys.exit(0 if failed == 0 else 1)
