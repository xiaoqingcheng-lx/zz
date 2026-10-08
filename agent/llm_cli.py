"""终端版对话大语言模型：循环问答，每轮都把之前所有聊天记录一起发给模型。配置读 config.ini。

运行：python llm_cli.py
退出：输入 exit / quit / q，空行回车，或按 Ctrl+C
"""
import sys
import time

from llm import TYPE_MS, ask_stream


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
        except SystemExit as e:           # ask_stream 用 sys.exit 报 HTTP 错误
            print("出错了：%s" % e)
        if parts:                         # 把本轮问答存进历史，供后面每一轮带上
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": "".join(parts)})
        print("\n")
    print("再见。")


if __name__ == "__main__":
    main()
