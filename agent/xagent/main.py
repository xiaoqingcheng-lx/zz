# -*- coding: utf-8 -*-
"""xAgent 入口：默认终端交互对话，--demo 一次性演示。

    python main.py                     # 交互模式（输入 exit 退出）
    python main.py --demo "提示词"     # 单次运行，完整打印工具调用过程
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xagent import run_agent  # noqa: E402


def demo(prompt: str) -> None:
    """一次性演示：完整展示 Agent 调用本地工具的全过程。"""
    print(f"用户：{prompt}")
    answer, _ = run_agent(prompt)
    print(f"\nxAgent：{answer}")


def interactive() -> None:
    print("xAgent（可调用本地 CLI，输入 exit 退出）\n")
    history: list = []
    while True:
        try:
            prompt = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt or prompt.lower() in ("exit", "quit", "q"):
            break
        answer, history = run_agent(prompt, history)
        print(f"xAgent：{answer}\n")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--demo":
        demo(args[1] if len(args) > 1 else "查看当前目录下有哪些文件")
    else:
        interactive()
