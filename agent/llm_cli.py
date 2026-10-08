"""终端版对话大语言模型：循环问答，每轮都把之前所有聊天记录一起发给模型。

单文件版，不依赖任何本地模块，只需要同目录下有 config.ini：

    [llm]
    base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key  = sk-你的key
    model    = qwen-plus

运行：python llm_cli.py
退出：输入 exit / quit / q，空行回车，或按 Ctrl+C
"""
import configparser
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path(__file__).with_name("config.ini")
TYPE_MS = 0.025     # 逐字显示时每个字之间的间隔
TIMEOUT = 120       # 单次请求超时（秒）

_CONFIG_HINT = """找不到配置文件：%s

请在脚本同目录新建 config.ini，内容如下（api_key 换成你自己的）：

[llm]
base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
api_key = sk-你的key
model = qwen-plus"""


def _post(messages, stream=False):
    """按 config.ini 拼一个 chat/completions 请求。"""
    cfg = configparser.ConfigParser()
    if not cfg.read(CONFIG, encoding="utf-8"):
        sys.exit(_CONFIG_HINT % CONFIG)
    s = cfg["llm"]
    return urllib.request.Request(
        s["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps({
            "model": s["model"],
            "stream": stream,
            "messages": messages,
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + s["api_key"],
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
