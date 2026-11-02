# -*- coding: utf-8 -*-
"""xAgent 入口：默认终端交互对话，--demo 一次性演示，--skills 看技能，--mcp 看 MCP。

    python main.py                     # 交互模式（输入 exit 退出）
    python main.py --demo "提示词"     # 单次运行，完整打印工具调用过程
    python main.py --skills            # 打印技能注册表与注入的 System Prompt 片段
    python main.py --mcp               # 打印 MCP 服务器连接结果与注册到的工具
    python main.py --tools             # 列出本轮可用的全部工具（本地 + MCP）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xagent import MCP, SKILLS, TOOL_SCHEMAS, run_agent  # noqa: E402


def show_skills() -> None:
    """打印技能注册结果（发现 → 注册 → 注入 Prompt 的中间产物）。"""
    print(SKILLS.summary())
    if SKILLS.skills:
        print("\n--- 注入 System Prompt 的技能清单 ---")
        print(SKILLS.prompt_section())
    else:
        print("\n（没有可用技能：请在 .agents\\skills\\ 下放置含 SKILL.md 的子目录）")


def show_mcp() -> None:
    """打印 MCP 连接与工具注册结果。"""
    print(f"配置文件：{MCP.config_path}")
    print()
    print(MCP.summary())
    if MCP.tools:
        print("\n--- 注册给 LLM 的 MCP 工具 ---")
        for t in MCP.tools.values():
            params = ", ".join((t.schema.get("properties") or {}).keys()) or "无参数"
            print(f"  {t.exposed:<24} [{t.server}] 参数：{params}")
            print(f"      原始工具名：{t.name}")


def show_tools() -> None:
    """列出本轮全部工具声明（本地 + MCP）。"""
    print(f"共 {len(TOOL_SCHEMAS)} 个工具：")
    for s in TOOL_SCHEMAS:
        fn = s["function"]
        desc = (fn.get("description") or "").replace("\n", " ")[:60]
        print(f"  - {fn['name']:<24} {desc}")


def demo(prompt: str) -> None:
    """一次性演示：完整展示 Agent 调用工具的全过程。"""
    print(f"用户：{prompt}")
    answer, _ = run_agent(prompt)
    print(f"\nxAgent：{answer}")


def interactive() -> None:
    print("xAgent（可调用本地工具、技能与 MCP 远程工具，输入 exit 退出）")
    print(SKILLS.summary())
    print(MCP.summary() + "\n")
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
    elif args and args[0] == "--skills":
        show_skills()
    elif args and args[0] == "--mcp":
        show_mcp()
    elif args and args[0] == "--tools":
        show_tools()
    else:
        interactive()
