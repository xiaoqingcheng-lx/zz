"""practice02 启动文件：流式对话 + 工具调用 + 本地文件操作。

把前几天的三块东西接成一条完整链路：

    你输入  →  DashScope 流式回复（逐字显示）
            →  模型决定调工具（function calling）
            →  MCP 客户端走 stdio 拉起 server.py
            →  server.py 里注册的 11 个工具（9 个文件操作 + getDate + isleapyear）
            →  工具结果回灌给模型  →  模型接着把话说完整

和 demo.py 的区别：demo.py 是「人按命令调工具」，本文件是「模型自己决定调哪个工具」。

运行（必须用 practice02 的 venv，里面装了 mcp）：
    .venv\\Scripts\\python.exe chat-stream-tool-fileops.py

对话里可用：
    /tools   看当前可用的工具
    /reset   清空上下文，重新开始
    /help    看这份说明
    exit     退出（quit / q 同）

API Key 读取顺序：同目录 config.ini → 上级目录（agent/config.ini）→ 内置 _secret.py。
"""

from __future__ import annotations

import asyncio
import configparser
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent          # practice02/
PARENT = HERE.parent                            # agent/

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
TIMEOUT = 180          # 单次请求超时（秒）
TYPE_MS = 0.012        # 逐字显示的间隔
MAX_ROUNDS = 12        # 一轮提问里最多允许模型连续调几次工具，防死循环
TOOL_TEXT_LIMIT = 4000  # 回灌给模型的单条工具结果上限，防上下文爆炸

LINE = "=" * 64

HELP = """\
【可用命令】
  /tools   列出当前接上的工具
  /reset   清空上下文（模型会忘记前面聊过的内容）
  /help    显示这份说明
  exit     退出（quit / q 也可以）

【能做什么】
直接说人话就行，模型会自己决定要不要调工具，例如：
  · 现在几点了
  · 看看 D:\\大语言模型\\agent\\practice02 下有哪些文件
  · 读一下 requirements.txt 的内容
  · 在 D:\\temp\\demo 下建个 hello.txt，写「你好」
  · 2028 年是闰年吗
  · 把刚才那个文件追加一行「第二行」
"""


# ---------------------------------------------------------------- 控制台
def setup_console() -> None:
    """把控制台切到 UTF-8，避免中文/emoji 在 GBK 控制台下直接崩。"""
    if os.name == "nt" and sys.stdout is not None and sys.stdout.isatty():
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            if k32.SetConsoleOutputCP(65001) and k32.SetConsoleCP(65001):
                for stream in (sys.stdin, sys.stdout, sys.stderr):
                    stream.reconfigure(encoding="utf-8", errors="replace")
                return
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.reconfigure(errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 配置
def load_config() -> tuple[str, str, str]:
    """取 (base_url, api_key, model)：本目录 → 上级目录 → 内置凭据。"""
    cfg = configparser.ConfigParser()
    for path in (HERE / "config.ini", PARENT / "config.ini"):
        if path.is_file():
            cfg.read(path, encoding="utf-8")
            break

    base_url = cfg.get("llm", "base_url", fallback="").strip() or DEFAULT_BASE_URL
    model = cfg.get("llm", "model", fallback="").strip() or DEFAULT_MODEL
    key = cfg.get("llm", "api_key", fallback="").strip()

    if not key or key.startswith("sk-你的"):
        try:
            sys.path.insert(0, str(PARENT))
            from _secret import key as builtin      # 打包/分发时用内置凭据
            key = builtin().strip()
        except Exception:
            key = ""
    return base_url, key, model


# ---------------------------------------------------------------- 工具桥接
def text_of(result) -> str:
    """从 CallToolResult 里取出纯文本。"""
    parts = [getattr(item, "text", "") for item in (getattr(result, "content", None) or [])]
    parts = [p for p in parts if p]
    if parts:
        return "\n".join(parts)
    return str(result)


def to_openai_tool(tool) -> dict:
    """MCP 的 Tool 定义 → OpenAI function calling 的 tools 项。"""
    schema = (getattr(tool, "input_schema", None)      # mcp 2.x 用蛇形命名
              or getattr(tool, "inputSchema", None)    # 兼容旧版/字典式对象
              or {"type": "object", "properties": {}})
    schema = {k: v for k, v in schema.items() if k != "title"}
    schema.setdefault("type", "object")
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (tool.description or tool.name)[:1024],
            "parameters": schema,
        },
    }


# ---------------------------------------------------------------- 流式请求
def post_stream(messages: list, tools: list, cfg: tuple[str, str, str]):
    """拼一个 stream=True 的 chat/completions 请求。"""
    base_url, key, model = cfg
    payload = {"model": model, "stream": True, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )


def stream_once(messages: list, tools: list, cfg: tuple, typing: bool):
    """跑一次流式请求，边吐字边攒工具调用。

    返回 (完整正文, [{"id","name","arguments"}, ...])。
    """
    body, calls = [], {}
    try:
        with urllib.request.urlopen(post_stream(messages, tools, cfg), timeout=TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    choice = json.loads(data)["choices"][0]
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue

                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    body.append(piece)
                    for ch in piece:
                        print(ch, end="", flush=True)
                        if typing:
                            time.sleep(TYPE_MS)

                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = slot["name"] or fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError("HTTP %s：%s" % (exc.code, detail[:300])) from None
    except urllib.error.URLError as exc:
        raise RuntimeError("网络不可达：%s" % exc.reason) from None

    ordered = [calls[i] for i in sorted(calls) if calls[i]["name"]]
    return "".join(body), ordered


async def call_tool(session: ClientSession, name: str, arguments: str) -> str:
    """把模型给的 JSON 参数交给 MCP 服务端执行，返回文本结果。"""
    try:
        args = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError as exc:
        return "参数不是合法 JSON：%s（原文：%s）" % (exc, arguments[:200])
    try:
        result = await session.call_tool(name, args)
    except Exception as exc:                       # 服务端异常不该让整轮对话挂掉
        return "工具执行失败：%s" % exc
    return text_of(result)


# ---------------------------------------------------------------- 一轮问答
async def run_turn(session: ClientSession, history: list, prompt: str,
                   tools: list, cfg: tuple, typing: bool) -> None:
    """一次提问可能触发多轮「模型说话 → 调工具 → 再说话」。"""
    history.append({"role": "user", "content": prompt})

    for round_no in range(1, MAX_ROUNDS + 1):
        print("AI：" if round_no == 1 else "\nAI（继续）：", end="", flush=True)
        content, calls = stream_once(history, tools, cfg, typing)
        print()

        if not calls:                              # 没有工具调用，本轮结束
            history.append({"role": "assistant", "content": content})
            return

        # 先把模型这一轮的「话 + 工具调用意图」记进历史
        history.append({
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {
                    "id": call["id"] or "call_%d_%d" % (round_no, i),
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
                }
                for i, call in enumerate(calls)
            ],
        })

        for i, call in enumerate(calls):
            call_id = call["id"] or "call_%d_%d" % (round_no, i)
            brief = call["arguments"].replace("\n", " ")[:120]
            print("  ⟳ %s(%s)" % (call["name"], brief), flush=True)
            output = await call_tool(session, call["name"], call["arguments"])
            preview = output.strip().splitlines()
            for row in preview[:6]:
                print("    " + row)
            if len(preview) > 6:
                print("    …（共 %d 行）" % len(preview))
            history.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": output[:TOOL_TEXT_LIMIT],
            })
    else:
        print("（工具调用次数达到上限 %d 次，本轮先停在这里）" % MAX_ROUNDS)


# ---------------------------------------------------------------- 入口
async def main() -> None:
    setup_console()
    cfg = load_config()
    if not cfg[1]:
        sys.exit("没有可用的 API Key：请在 %s 下建 config.ini 填 [llm] api_key。" % HERE)

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "server.py")],
        cwd=str(HERE),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            tools = [to_openai_tool(t) for t in listed.tools]
            typing = sys.stdin is not None and sys.stdin.isatty()

            print(LINE)
            print("practice02 · 流式对话 + 工具调用")
            print("MCP 服务：%s   协议：%s" % (init.server_info.name or "?", init.protocol_version))
            print("模型：%-10s  可用工具：%d 个" % (cfg[2], len(tools)))
            print(LINE)
            print("直接说人话就行；/tools 看工具，/reset 清上下文，exit 退出。\n")

            history: list[dict] = []
            while True:
                try:
                    prompt = input("你：").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                if not prompt:
                    continue
                if prompt.lower() in ("exit", "quit", "q"):
                    break
                if prompt == "/tools":
                    for t in listed.tools:
                        print("  · %-13s %s" % (t.name, (t.description or "").splitlines()[0]))
                    print()
                    continue
                if prompt == "/reset":
                    history.clear()
                    print("上下文已清空。\n")
                    continue
                if prompt == "/help":
                    print(HELP)
                    continue

                try:
                    await run_turn(session, history, prompt, tools, cfg, typing)
                except RuntimeError as exc:
                    print("出错了：%s\n" % exc)
                    history.pop()            # 这一轮没成功，别把半截记进历史
                print()

    print("再见。")


if __name__ == "__main__":
    asyncio.run(main())
