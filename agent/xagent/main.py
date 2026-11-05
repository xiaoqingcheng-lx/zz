# -*- coding: utf-8 -*-
"""xAgent 入口：默认终端交互对话，--demo 一次性演示，--skills 看技能，--mcp 看 MCP。

    python main.py                     # 交互模式（输入 /help 看命令，exit 退出）
    python main.py --demo "提示词"     # 单次运行，完整打印工具调用过程
    python main.py --skills            # 打印技能注册表与注入的 System Prompt 片段
    python main.py --mcp               # 打印 MCP 服务器连接结果与注册到的工具
    python main.py --tools             # 列出本轮可用的全部工具（本地 + MCP）
    python main.py --context           # 只看上下文用量与归档情况

交互命令：
    /compact   手动触发上下文压缩（归档原始记录 → LLM 生成摘要 → 替换历史）
    /context   查看上下文用量、阈值与归档文件
    /help      帮助
    /exit      退出
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import context_manager as cm                                  # noqa: E402
from xagent import (CONTEXT, MCP, SKILLS, TOOL_SCHEMAS,       # noqa: E402
                    compact_session, run_agent, system_prompt)

USE_COLOR = cm.enable_ansi()

HELP_TEXT = """可用命令：
  /compact   压缩当前会话上下文：先把原始记录完整归档，再让 LLM 生成摘要替换历史
  /context   查看上下文用量、阈值状态与归档文件列表
  /help      显示本帮助
  /exit      退出（也可以输入 exit / quit / q）"""


def _all_messages(history: list) -> list:
    """状态栏要计量的完整上下文：System Prompt + 对话历史 + 工具消息。"""
    return [{"role": "system", "content": system_prompt()}] + list(history)


def _status_line(history: list) -> str:
    return CONTEXT.status_bar(_all_messages(history), USE_COLOR)


def show_status(history: list) -> None:
    """在醒目位置打印一行上下文状态（含窗口大小、百分比、占用条）。"""
    print(_status_line(history))


def show_context_detail(history: list) -> None:
    """上下文用量明细 + 归档列表。"""
    msgs = _all_messages(history)
    used = CONTEXT.used_tokens(msgs)
    ratio = CONTEXT.ratio(used)
    print()
    print("─" * 46)
    print(f"模型            {CONTEXT.model}")
    print(f"上下文窗口      {cm.format_k(CONTEXT.window)} Tokens"
          + ("（默认值，未能识别模型）" if CONTEXT.window_is_default else ""))
    print(f"当前占用        {cm.format_k(used)} Tokens / {ratio * 100:.1f}%"
          f"（来源：{'API usage' if CONTEXT.api_source == 'api' else '字符估算'}）")
    print(f"告警阈值        {cm.WARN_RATIO * 100:.0f}%"
          + ("　→ 已触发，需 /compact" if CONTEXT.blocked else "　→ 未触发"))
    print(f"消息条数        {len(history)}（不含 System Prompt）")
    print(f"归档目录        {CONTEXT.archive_dir}")
    archives = cm.list_archives(CONTEXT.archive_dir)
    if archives:
        print(f"已有归档        {len(archives)} 个")
        for p in archives[:5]:
            size = p.stat().st_size / 1024
            print(f"  - {p.stem}  ({size:.1f} KB)")
        if len(archives) > 5:
            print(f"  … 另有 {len(archives) - 5} 个")
    else:
        print("已有归档        0 个（执行 /compact 后会生成）")
    print("─" * 46)


def do_compact(history: list) -> list:
    """执行 /compact：成功后返回替换后的历史；失败保留原历史。"""
    if not history:
        print("ℹ️ 当前会话还没有历史消息，不需要压缩。")
        return history

    before = cm.estimate_messages_tokens(history)
    print(f"\n⚙️ 开始压缩上下文（{len(history)} 条消息，约 {cm.format_k(before)} Tokens）"
          f"——期间不执行任何工具调用，也不处理新任务。")
    try:
        new_history, info = compact_session(history, ctx=CONTEXT, verbose=True)
    except cm.CompactError as e:
        print(cm.colorize(f"❌ 压缩失败：{e}", "red", USE_COLOR))
        print("   原有上下文完整保留，可直接重新执行 /compact。")
        return history
    except Exception as e:                       # 网络 / API 异常
        print(cm.colorize(f"❌ 压缩失败：{e}", "red", USE_COLOR))
        print("   原有上下文完整保留，可直接重新执行 /compact。")
        return history

    after = cm.estimate_messages_tokens(new_history)
    print(cm.colorize("✅ 压缩完成", "green", USE_COLOR))
    print(f"   历史消息：{info['replaced']} 条 → {len(new_history)} 条（摘要）")
    print(f"   Token：约 {cm.format_k(before)} → 约 {cm.format_k(after)}")
    print(f"   归档编号：{info['id']}")
    print(f"   归档文件：{info['path']}")
    print("   摘要末尾已追加归档说明；需要旧细节时可让 Agent 调用 recallContext 检索。\n")
    return new_history


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
    answer, history = run_agent(prompt, ctx=CONTEXT)
    print(f"\nxAgent：{answer}")
    print()
    show_status(history)


def interactive() -> None:
    print("xAgent（可调用本地工具、技能与 MCP 远程工具；/help 看命令，exit 退出）")
    print(SKILLS.summary())
    print(MCP.summary())
    print(f"上下文归档目录：{CONTEXT.archive_dir}\n")

    history: list = []
    show_status(history)

    while True:
        # ---- 输入闸门：达到 70% 后只接受命令 ----
        warn = CONTEXT.warning_line(_all_messages(history), USE_COLOR)
        if warn:
            print(warn)
        try:
            prompt = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not prompt:
            continue
        low = prompt.lower()
        if low in ("exit", "quit", "q", "/exit", "/quit"):
            break

        # ---- 命令 ----
        if low.startswith("/"):
            if low == "/compact":
                history = do_compact(history)
            elif low in ("/context", "/status"):
                show_context_detail(history)
            elif low in ("/help", "/?"):
                print(HELP_TEXT)
            else:
                print(f"未知命令：{prompt}（输入 /help 查看可用命令）")
            show_status(history)
            continue

        # ---- 普通提示词：达到阈值就拒绝 ----
        if CONTEXT.blocked:
            print(cm.colorize(
                f"⛔ 上下文已占用 {CONTEXT.ratio(CONTEXT.used_tokens(_all_messages(history))) * 100:.1f}%，"
                f"已暂停处理新任务。请先执行 /compact。", "red", USE_COLOR))
            continue

        answer, history = run_agent(prompt, history, ctx=CONTEXT)
        print(f"xAgent：{answer}\n")

        # ---- 每次响应后检查上下文用量（含工具消息），越过 70% 就挂闸门 ----
        used = CONTEXT.used_tokens(_all_messages(history))
        CONTEXT.update_blocked(used)
        show_status(history)


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
    elif args and args[0] == "--context":
        show_context_detail([])
    else:
        interactive()
