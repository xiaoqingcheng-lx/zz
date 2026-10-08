"""终端版对话大语言模型：循环问答，每轮都把之前所有聊天记录一起发给模型。

单文件版，不依赖任何本地模块。打包成 exe 分发时自带内置凭据，对方双击即用；
自己开发时可在同目录放 config.ini 覆盖内置值：

    [llm]
    base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key  = sk-你的key
    model    = qwen-plus

运行：python llm_cli.py
退出：输入 exit / quit / q，空行回车，或按 Ctrl+C
"""
import configparser
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _config_path():
    """config.ini 的位置。

    打包成 exe 后就在 exe 所在目录找（方便对方换成自己的 key）；
    源码运行时找脚本同目录。
    """
    if getattr(sys, "frozen", False):              # PyInstaller 打包后
        return Path(sys.executable).with_name("config.ini")
    return Path(__file__).with_name("config.ini")


CONFIG = _config_path()
TYPE_MS = 0.025     # 逐字显示时每个字之间的间隔
TIMEOUT = 120       # 单次请求超时（秒）

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"

_KEY_HINT = """没有可用的 API Key。

请在同目录新建 config.ini 填上你自己的，格式：

[llm]
base_url = %s
api_key = sk-你的key
model = %s""" % (DEFAULT_BASE_URL, DEFAULT_MODEL)


def _setup_console():
    """别让中文或 emoji 把程序打崩。

    Windows 控制台默认 GBK，而模型回复里常带 emoji（如 ✅），打印时会抛
    UnicodeEncodeError 直接退出。这里优先把控制台切成 UTF-8；切不了就退化成
    把编不出来的字符换成 "?"，总之不能再崩。
    """
    if os.name == "nt" and sys.stdout is not None and sys.stdout.isatty():
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            if k32.SetConsoleOutputCP(65001) and k32.SetConsoleCP(65001):
                for stream in (sys.stdin, sys.stdout, sys.stderr):
                    stream.reconfigure(encoding="utf-8", errors="replace")
                return
        except Exception:
            pass                       # 切不动就走下面的兜底
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.reconfigure(errors="replace")
        except Exception:
            pass


def _load_config():
    """取 (base_url, api_key, model)。

    config.ini 存在且填了就优先用它，没填的字段回落内置值；
    api_key 缺失时尝试用内置凭据（打包成 exe 分发时走这条）。
    """
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG, encoding="utf-8")            # 文件不存在就跳过，不算错

    base_url = cfg.get("llm", "base_url", fallback="").strip() or DEFAULT_BASE_URL
    model = cfg.get("llm", "model", fallback="").strip() or DEFAULT_MODEL

    key = cfg.get("llm", "api_key", fallback="").strip()
    if not key or key.startswith("sk-你的"):      # 没填 / 还是示例占位符
        try:
            from _secret import key as builtin    # 内置凭据，运行时还原
            key = builtin().strip()
        except Exception:
            key = ""
    return base_url, key, model


def _post(messages, stream=False):
    """按配置拼一个 chat/completions 请求。"""
    base_url, key, model = _load_config()
    if not key:
        sys.exit(_KEY_HINT)
    return urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps({
            "model": model,
            "stream": stream,
            "messages": messages,
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )


def ask_stream(prompt, history=()):
    """逐块产出回复内容（走服务端 SSE 流）。

    history 为 [{"role": "user"/"assistant", "content": "..."}]；
    传空（默认）就是单轮、不带任何上文。
    """
    messages = list(history) + [{"role": "user", "content": prompt}]
    try:
        with urllib.request.urlopen(_post(messages, stream=True), timeout=TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                piece = (json.loads(data)["choices"][0].get("delta") or {}).get("content")
                if piece:
                    yield piece
    except urllib.error.HTTPError as e:
        sys.exit("请求失败 HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")))


def main():
    _setup_console()
    typing = sys.stdout.isatty()          # 终端里逐字流；被管道/重定向时直接快吐
    print("对话大语言模型（输入 exit 退出，会记得前面聊过的内容）\n")

    history = []                          # 累积全部聊天记录，每轮一起发过去
    while True:
        try:
            prompt = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt or prompt.lower() in ("exit", "quit", "q"):
            break
        print("AI：", end="", flush=True)
        parts = []
        try:
            for piece in ask_stream(prompt, history):
                parts.append(piece)
                if typing:
                    for ch in piece:
                        print(ch, end="", flush=True)
                        time.sleep(TYPE_MS)
                else:
                    print(piece, end="", flush=True)
        except SystemExit as e:           # ask_stream 用 sys.exit 报 HTTP / 配置错误
            print("出错了：%s" % e)
        if parts:                         # 把本轮问答存进历史，供后面每一轮带上
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": "".join(parts)})
        print("\n")
    print("再见。")


if __name__ == "__main__":
    main()
