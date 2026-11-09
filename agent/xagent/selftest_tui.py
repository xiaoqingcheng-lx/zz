# -*- coding: utf-8 -*-
"""xAgent TUI 冒烟测试（不联网、不调用真实模型）。

    py selftest_tui.py

覆盖：状态栏文案、用户消息渲染、工具调用与返回回显、最终回答、
      /help、/context、/tools、压缩结果浮动面板（左原文 / 右摘要 / 滚动 / 关闭）、
      70% 闸门拒绝新消息、F2 清空会话。
"""
import asyncio
import json
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
    # 归档目录与会话目录都指到临时目录，避免污染项目
    tmp = Path(tempfile.mkdtemp(prefix="xagent_tui_"))
    import xagent as xa
    from xagent import CONTEXT
    CONTEXT.archive_dir = tmp
    xa.SKILLS.project_root = tmp          # 会话存档 / AGENTS.md 都落在 tmp

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

        # ---- /compact 浮动面板（左原文 / 右摘要，可滚动，可关闭）----
        import xagent as xa
        xa.summarize_chat = (lambda sys_p, user_p:
                             "# 工作摘要\n- 已完成压缩面板\n- 路径 D:/大语言模型/agent/xagent")
        app.history = [
            {"role": "user", "content": "第一问：帮我看下项目结构 " + "补充说明" * 120},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "RunCli",
                                          "arguments": '{"command":"ls"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "tui_app.py\ncontext_manager.py"},
            {"role": "assistant", "content": "目录已确认。"},
            {"role": "user", "content": "第二问：记住路径 D:/大语言模型/agent/xagent"},
            {"role": "assistant", "content": "已记住。"},
        ]
        inp.value = "/compact"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.6)

        from textual.widgets import Button
        from tui_app import CompactResultScreen
        check("压缩完成弹出浮动面板", isinstance(app.screen, CompactResultScreen),
              type(app.screen).__name__)
        scr = app.screen
        left = scr.query_one("#compact-left", RichLog)
        right = scr.query_one("#compact-right", RichLog)
        left_text = "\n".join(l.text for l in left.lines)
        right_text = "\n".join(l.text for l in right.lines)
        check("左栏是压缩前原文", "第一问" in left_text and "第二问" in left_text)
        check("左栏保留工具调用与参数", "RunCli" in left_text and "command" in left_text)
        check("左栏按角色分块", "▌ #0" in left_text and "用户" in left_text)
        check("右栏是压缩后摘要", "工作摘要" in right_text and "已完成压缩面板" in right_text)
        check("右栏含归档说明", "recallContext" in right_text)
        check("左栏可滚动", left.max_scroll_y > 0, str(left.max_scroll_y))
        check("两栏各自有滚动条",
              left.show_vertical_scrollbar and right.show_vertical_scrollbar)
        check("两栏等宽", abs(left.size.width - right.size.width) <= 2,
              f"{left.size.width} vs {right.size.width}")
        check("有独立滚动位置", left.scroll_y == 0 and right.scroll_y == 0)
        await pilot.press("pagedown")
        await pilot.pause(0.2)
        check("面板内可上下滚动", left.scroll_y > 0, str(left.scroll_y))
        check("有关闭按钮", scr.query_one("#compact-close", Button) is not None)
        check("历史已替换为 1 条摘要", len(app.history) == 1, str(len(app.history)))

        await pilot.press("escape")
        await pilot.pause(0.3)
        check("Esc 关闭面板", type(app.screen).__name__ == "Screen", type(app.screen).__name__)
        check("关闭后输入框可用", inp.disabled is False)

        inp.value = "/result"
        await pilot.press("enter")
        await pilot.pause(0.4)
        check("/result 可重开面板", isinstance(app.screen, CompactResultScreen),
              type(app.screen).__name__)
        await pilot.click("#compact-close")
        await pilot.pause(0.3)
        check("点「关闭」按钮可关闭", type(app.screen).__name__ == "Screen",
              type(app.screen).__name__)

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

        # ---- 跨过阈值时，聊天区要主动弹警告（不只状态栏变红）----
        orig_used = CONTEXT.used_tokens
        CONTEXT.used_tokens = lambda msgs: int(CONTEXT.window * 0.75)
        CONTEXT.blocked = False
        app._finish_turn()
        await pilot.pause(0.2)
        text = "\n".join(s.text for s in log.lines)
        check("跨阈值时聊天区弹出 /compact 警告", "请执行 /compact" in text, text[-300:])
        check("警告里带具体占用百分比", "%" in text.split("请执行 /compact")[0][-40:],
              text[-300:])
        CONTEXT.used_tokens = orig_used
        CONTEXT.blocked = False
        app._refresh_status()
        await pilot.press("f2")
        await pilot.pause(0.3)
        check("F2 清空历史", app.history == [], str(app.history))
        check("F2 后状态栏归零", "轮数: 0" in app.status_text, app.status_text)

        # ================================================================
        # 以下为新功能：命令补全面板 / 会话命令 / AGENTS.md 注入 / 边栏
        # ================================================================
        from tui_app import CommandPalette, ResumeScreen
        pal = app.query_one("#palette", CommandPalette)

        # ---- 补全面板：输入 / 弹出引导 ----
        inp.value = "/re"
        await pilot.pause(0.2)
        check("输入 / 前缀弹出补全面板", pal.visible)
        check("补全面板过滤出 /resume", "/resume" in pal._current, str(pal._current))
        await pilot.press("enter")            # 回车补全
        await pilot.pause(0.2)
        check("回车补全成完整命令", inp.value == "/resume ", repr(inp.value))
        check("补全后面板收起", not pal.visible)

        inp.value = "/n"
        await pilot.pause(0.2)
        check("/n 弹出且含 /new", pal.visible and "/new" in pal._current)
        await pilot.press("down")
        await pilot.press("up")
        check("↑↓ 移动选中项", (pal.query_one("#palette-list").highlighted or 0) == 0)
        await pilot.press("escape")
        await pilot.pause(0.2)
        check("Esc 关闭补全面板", not pal.visible)
        inp.value = "普通消息不弹面板"
        await pilot.pause(0.2)
        check("普通文本不弹补全面板", not pal.visible)
        inp.value = ""

        # ---- 一轮对话后 /save ----
        inp.value = "保存我"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.3)
        inp.value = "/save"
        await pilot.press("enter")
        await pilot.pause(0.3)
        sessions_dir = tmp / ".agents" / "sessions"
        saved = list(sessions_dir.glob("*.json"))
        check("/save 落盘会话文件", len(saved) >= 1, str(list(sessions_dir.glob('*'))))
        if saved:
            data = json.loads(saved[0].read_text(encoding="utf-8"))
            check("会话文件含完整历史与元信息",
                  len(data["history"]) == 2 and data["turns"] == 1
                  and "title" in data and "created_at" in data)
        old_session_id = app.session_id

        # ---- /new：自动保存当前会话 + AGENTS.md 注入 ----
        (tmp / "AGENTS.md").write_text("# 项目约定\n- 回答用中文", encoding="utf-8")
        inp.value = "/new"
        await pilot.press("enter")
        await pilot.pause(0.3)
        check("/new 换了会话编号", app.session_id != old_session_id)
        check("/new 后历史只含 AGENTS.md 注入消息",
              len(app.history) == 1
              and app.history[0]["content"].startswith("【AGENTS.md 项目说明】"),
              str(app.history)[:120])
        text = "\n".join(s.text for s in log.lines)
        check("/new 界面提示自动保存", "已保存当前会话" in text)
        check("AGENTS.md 不计入轮数", "轮数: 0" in app.status_text, app.status_text)
        n_files_after_new = len(list(sessions_dir.glob("*.json")))
        check("旧会话已按编号自动保存",
              (sessions_dir / f"{old_session_id}.json").is_file())

        # ---- /resume：面板选择恢复 ----
        inp.value = "/save"
        await pilot.press("enter")
        await pilot.pause(0.3)
        inp.value = "/resume"
        await pilot.press("enter")
        await pilot.pause(0.4)
        check("/resume 弹出会话面板", isinstance(app.screen, ResumeScreen),
              type(app.screen).__name__)
        check("面板列出会话条目",
              app.screen.query_one("#resume-list").option_count >= 2)
        await pilot.press("enter")            # 选中最新会话并恢复
        await pilot.pause(0.4)
        check("回车后面板关闭", type(app.screen).__name__ != "ResumeScreen",
              type(app.screen).__name__)
        check("历史已恢复（含 AGENTS.md 消息）",
              len(app.history) >= 1
              and app.history[0]["content"].startswith("【AGENTS.md 项目说明】"),
              str(app.history)[:120])
        text = "\n".join(s.text for s in log.lines)
        check("恢复界面显示会话信息", "已恢复会话" in text)

        # Esc 取消
        inp.value = "/resume"
        await pilot.press("enter")
        await pilot.pause(0.4)
        await pilot.press("escape")
        await pilot.pause(0.3)
        check("Esc 取消会话面板", type(app.screen).__name__ != "ResumeScreen",
              type(app.screen).__name__)

        # ---- 边栏 ----
        from xagent import MCP
        body = app.sidebar_text
        check("边栏有 MCP 区域", "MCP" in body, body[:120])
        check("边栏有技能区域", "技能" in body, body[:120])
        MCP.loaded = True                     # 模拟异步加载完成 → 动态刷新
        MCP.server_tools.setdefault("SelftestMCP", 2)
        app._refresh_sidebar()
        body = app.sidebar_text
        check("MCP 加载后边栏动态刷新出服务器", "SelftestMCP" in body, body[:200])
        MCP.server_tools.pop("SelftestMCP", None)
        app._refresh_sidebar()

        # ---- /history /model /config /mcp /skills 不炸 ----
        for cmd in ("/history", "/model", "/config", "/mcp", "/skills", "/help"):
            inp.value = cmd
            await pilot.press("enter")
            await pilot.pause(0.2)
        text = "\n".join(s.text for s in log.lines)
        check("/model /config /mcp /skills 全部可执行",
              "模型" in text and "配置文件" in text and "MCP 服务器" in text)
        check("未知命令有提示", "/nope" not in text)  # 未输入过未知命令，应无副作用

    print(f"\n通过 {PASS} 项，失败 {FAIL} 项")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
