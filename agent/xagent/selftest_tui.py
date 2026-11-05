# -*- coding: utf-8 -*-
"""xAgent TUI 冒烟测试（不联网、不调用真实模型）。

    py selftest_tui.py

覆盖：状态栏文案、用户消息渲染、工具调用与返回回显、最终回答、
      /help、/context、70% 闸门拒绝新消息、F2 清空会话。
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import context_manager as cm                     # noqa: E402
from tui_app import XAgentTUI                    # noqa: E402

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def fake_agent(prompt, history=(), verbose=False, ctx=None, on_event=None):
    """假 Agent：先报告一次工具调用 + 返回，再给出最终回答。"""
    if on_event:
        on_event({"type": "tool_call", "name": "RunCli", "args": {"command": "ls"}})
        on_event({"type": "tool_result", "name": "RunCli",
                  "result": "main.py\ntui_app.py", "is_error": False})
    new_hist = list(history) + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": f"收到：{prompt}"},
    ]
    return f"收到：{prompt}", new_hist


async def main() -> int:
    # 归档目录指到临时目录，避免污染项目
    tmp = Path(tempfile.mkdtemp(prefix="xagent_tui_"))
    from xagent import CONTEXT
    CONTEXT.archive_dir = tmp

    app = XAgentTUI()
    app.run_hook = fake_agent

    async with app.run_test(size=(130, 32)) as pilot:
        from textual.widgets import Input, RichLog, Static

        log = app.query_one("#chatlog", RichLog)
        inp = app.query_one("#prompt", Input)
        await pilot.pause(0.3)

        # ---- 状态栏 ----
        status = app.status_text
        check("状态栏含模型名", "模型: " in status, status)
        check("状态栏含上下文窗口 k", "/128k" in status or "k " in status, status)
        check("状态栏含占用百分比", "%" in status, status)
        check("状态栏含工具数量", "工具: " in status, status)
        check("状态栏含占用条", "█" in status or "░" in status, status)

        # ---- 一轮对话：工具回显 + 回答 ----
        inp.value = "列一下文件"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.3)

        text = "\n".join(s.text for s in log.lines)
        check("用户消息已渲染", "你：列一下文件" in text, text[-200:])
        check("工具调用已回显", "RunCli" in text, text[-300:])
        check("工具参数已回显", "command" in text, text[-300:])
        check("工具返回已回显", "tui_app.py" in text, text[-300:])
        check("最终回答已渲染", "xAgent：收到：列一下文件" in text, text[-300:])
        check("历史已沉淀 2 条", len(app.history) == 2, str(len(app.history)))
        check("轮数显示为 1", "轮数: 1" in app.status_text, app.status_text)
        check("输入框已恢复可用", inp.disabled is False)

        # ---- /help ----
        inp.value = "/help"
        await pilot.press("enter")
        await pilot.pause(0.3)
        text = "\n".join(s.text for s in log.lines)
        check("/help 输出命令列表", "/compact" in text and "/context" in text)

        # ---- /context ----
        inp.value = "/context"
        await pilot.press("enter")
        await pilot.pause(0.3)
        text = "\n".join(s.text for s in log.lines)
        check("/context 显示占用与归档", "上下文" in text and "归档" in text)

        # ---- /tools ----
        inp.value = "/tools"
        await pilot.press("enter")
        await pilot.pause(0.3)
        text = "\n".join(s.text for s in log.lines)
        check("/tools 列出工具", "RunCli" in text and "个工具" in text)

        # ---- 70% 闸门 ----
        from xagent import CONTEXT
        CONTEXT.blocked = True
        before = len(app.history)
        inp.value = "再问一个问题"
        await pilot.press("enter")
        await pilot.pause(0.3)
        text = "\n".join(s.text for s in log.lines)
        check("闸门拒绝普通消息", "⛔" in text and "已暂停处理新消息" in text, text[-300:])
        check("闸门期间不改历史", len(app.history) == before, str(len(app.history)))
        check("状态栏提示 /compact", "请 /compact" in app.status_text, app.status_text)
        CONTEXT.blocked = False
        app._refresh_status()

        # ---- F2 清空 ----
        await pilot.press("f2")
        await pilot.pause(0.3)
        check("F2 清空历史", app.history == [], str(app.history))
        check("F2 后状态栏归零", "轮数: 0" in app.status_text, app.status_text)

    print(f"\n通过 {PASS} 项，失败 {FAIL} 项")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
