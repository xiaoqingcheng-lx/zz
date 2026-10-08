"""一次性大语言模型：配置读 config.ini，提示词进，回复逐字流出，不带任何多余输出。

用法：
    python llm.py "你好"          # 参数传提示词
    echo "你好" | python llm.py   # 管道传提示词
    python llm.py                 # 直接运行，会提示你输入
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


def _post(messages, stream=False):
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG, encoding="utf-8")
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
        with urllib.request.urlopen(_post(messages, stream=True), timeout=120) as resp:
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
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])          # 命令行参数
    elif sys.stdin.isatty():
        try:
            prompt = input("请输入提示词: ")      # 交互式运行（VS Code 里直接运行走这里）
        except (EOFError, KeyboardInterrupt):
            prompt = ""
    else:
        prompt = sys.stdin.read()                # 管道/重定向
    if not prompt.strip():
        sys.exit('没有收到提示词。用法: python llm.py "你的提示词"')
    typing = sys.stdout.isatty()      # 终端里逐字流，管道/重定向时直接快吐，不拖慢
    for piece in ask_stream(prompt):
        if typing:
            for ch in piece:
                print(ch, end="", flush=True)
                time.sleep(TYPE_MS)
        else:
            print(piece, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
