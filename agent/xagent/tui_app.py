# -*- coding: utf-8 -*-
"""xAgent · Textual TUI。

和 `main.py` 的命令行版是同一套内核（xagent.py），只是把「打印」换成界面：
    · 顶部状态栏：模型 / 轮数 / 工具数量 / 上下文 已用k / 窗口k · 百分比 · 占用条
    · 中部聊天区：用户消息、工具调用（🔧 调用哪个工具、参数）、工具返回（📤 摘要）、最终回答
    · 底部输入框：Enter 发送，支持 /compact /context /help，F2 清空会话，ctrl+q 退出

上下文压缩与命令行版共用 `context_manager.py`：
    · 达到模型窗口 70% 自动挂闸门，普通消息被拒绝，只接受 /compact；
    · /compact 先归档原始对话到 .agents/context/<编号>.jsonl，成功后才用摘要替换历史；
    · 压缩失败时原历史一条不动，可直接重试。

启动：
    py tui_app.py          （或双击 xAgent对话.bat）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.markup import escape                              # noqa: E402
from textual import work                                   # noqa: E402
from textual.app import App, ComposeResult                  # noqa: E402
from textual.widgets import Footer, Header, Input, RichLog, Static  # noqa: E402

import context_manager as cm                                # noqa: E402
from xagent import (CONTEXT, LOCAL_SCHEMAS, MCP, SKILLS,    # noqa: E402
                    compact_session, run_agent, system_prompt)

HELP = (
    "[b]可用命令[/]\n"
    "  [b cyan]/compact[/]  压缩上下文（先归档原文，再让 LLM 生成摘要替换历史）\n"
    "  [b cyan]/context[/]  查看上下文用量、阈值状态与归档文件\n"
    "  [b cyan]/tools[/]    查看当前可调用的全部工具（本地 + MCP）\n"
    "  [b cyan]/help[/]     本帮助\n"
    "  [b cyan]exit[/]      退出（或 ctrl+q）\n"
)

CSS = """
#statusbar {
    height: 1;
    padding: 0 1;
    background: $panel;
    color: $text-muted;
}
#chatlog {
    border: round $primary;
    padding: 0 1;
}
#prompt {
    border: round $accent;
}
"""


class XAgentTUI(App):
    """xAgent 的全屏界面：带工具调用过程显示 + 上下文状态栏。"""

    TITLE = "xAgent"
    SUB_TITLE = "本地工具 + MCP 远程工具 + 技能 · Textual"

    CSS = CSS
    BINDINGS = [
        ("f2", "clear_chat", "清空会话"),
        ("ctrl+l", "clear_chat", "清空会话"),
        ("ctrl+q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.history: list = []       # 与命令行版同结构：含 tool_calls 与 role=tool 的完整轨迹
        self.busy = False             # 正在等 LLM / 跑工具 / 压缩
        self.status_text = ""         # 供自测断言
        self.run_hook = run_agent     # 自测时可替换为假实现

    # ------------------------------------------------------------------ #
    # 界面结构
    # ------------------------------------------------------------------ #
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="statusbar")
        yield RichLog(id="chatlog", highlight=False, markup=True, wrap=True)
        yield Input(
            placeholder="输入消息，Enter 发送（/compact 压缩上下文 ／ /help 帮助 ／ F2 清空）",
            id="prompt",
        )
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#chatlog", RichLog)
        log.write("[b cyan]xAgent[/]（可调用本地工具、技能与 MCP 远程工具）")
        for line in (SKILLS.summary() or "").splitlines():
            log.write(f"[dim]{escape(line)}[/]")
        for line in (MCP.summary() or "").splitlines():
            log.write(f"[dim]{escape(line)}[/]")
        log.write(f"[dim]上下文归档目录：{escape(str(CONTEXT.archive_dir))}[/]")
        log.write("[dim]Enter 发送 ｜ /compact 压缩 ｜ /context 用量 ｜ F2 清空 ｜ ctrl+q 退出[/]\n")
        self._refresh_status()
        self.query_one("#prompt", Input).focus()

    # ------------------------------------------------------------------ #
    # 状态栏
    # ------------------------------------------------------------------ #
    def _messages(self) -> list:
        """状态栏要计量的完整上下文：System Prompt + 历史（含工具消息）。"""
        return [{"role": "system", "content": system_prompt()}] + list(self.history)

    def _turns(self) -> int:
        """轮数 = 用户提问条数（压缩摘要那条不计入）。"""
        return sum(
            1 for m in self.history
            if m.get("role") == "user"
            and not str(m.get("content") or "").startswith(cm.SUMMARY_HEADER)
        )

    def _refresh_status(self) -> None:
        used = CONTEXT.used_tokens(self._messages())
        ratio = CONTEXT.ratio(used)
        color = "green" if ratio < 0.5 else ("yellow" if ratio < cm.WARN_RATIO else "red")
        blocks = max(0, min(10, int(round(ratio * 10))))
        meter = "█" * blocks + "░" * (10 - blocks)
        tail = "（默认）" if CONTEXT.window_is_default else ""
        local_n, mcp_n = len(LOCAL_SCHEMAS), len(MCP.tools)
        if self.busy:
            state = "[b yellow]运行中…[/]"
        elif CONTEXT.blocked:
            state = "[b red]← 请 /compact[/]"
        else:
            state = "就绪"
        text = (
            f"模型: {CONTEXT.model} ｜ 轮数: {self._turns()} ｜ "
            f"工具: {local_n + mcp_n}（本地 {local_n} / MCP {mcp_n}） ｜ "
            f"上下文 [{color}]{cm.format_k(used)}/{cm.format_k(CONTEXT.window)}{tail} · "
            f"{ratio * 100:.1f}% {meter}[/] ｜ {state}"
        )
        self.status_text = text
        self.query_one("#statusbar", Static).update(text)

    # ------------------------------------------------------------------ #
    # 输入处理
    # ------------------------------------------------------------------ #
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        log = self.query_one("#chatlog", RichLog)

        if text.lower() in ("exit", "quit", "q", "/exit", "/quit"):
            self.exit()
            return
        if self.busy:                            # 上一轮没结束，避免并发
            log.write("[b red]⏳ 正在执行中，请稍候…[/]")
            return

        if text.startswith("/"):
            cmd = text.lower()
            if cmd in ("/compact", "/compress"):
                self._start_compact(log)
            elif cmd in ("/context", "/status"):
                self._show_context(log)
            elif cmd == "/tools":
                self._show_tools(log)
            elif cmd in ("/help", "/?"):
                log.write(HELP)
            else:
                log.write(f"[b red]未知命令[/]：{escape(text)}（输入 /help 查看可用命令）")
            return

        if CONTEXT.blocked:                      # 70% 闸门：只接受 /compact
            pct = CONTEXT.ratio(CONTEXT.used_tokens(self._messages())) * 100
            log.write(f"[b red]⛔ 上下文已占用 {pct:.1f}%，已暂停处理新消息。[/]"
                      f"请先输入 [b cyan]/compact[/] 压缩上下文。")
            self._refresh_status()
            return

        log.write(f"[b green]你：[/]{escape(text)}")
        self.busy = True
        self.query_one("#prompt", Input).disabled = True
        self._refresh_status()
        self._reply_worker(text, log)

    # ------------------------------------------------------------------ #
    # 一轮对话：后台线程跑 run_agent，工具调用实时回显
    # ------------------------------------------------------------------ #
    @work(thread=True, exclusive=True)
    def _reply_worker(self, prompt: str, log: RichLog) -> None:
        """后台线程：LLM 推理 + 工具执行；DOM 操作一律 call_from_thread 回主线程。"""

        def on_event(ev: dict) -> None:
            if ev["type"] == "tool_call":
                args = json.dumps(ev["args"], ensure_ascii=False)
                if len(args) > 200:
                    args = args[:200] + "…"
                self.call_from_thread(
                    log.write,
                    f"  [b cyan]🔧 {escape(ev['name'])}[/] [dim]{escape(args)}[/]",
                )
            elif ev["type"] == "tool_result":
                text = (ev.get("result") or "").replace("\n", " ")
                if len(text) > 180:
                    text = text[:180] + "…"
                mark = "[b red]📤[/]" if ev.get("is_error") else "[dim]📤[/]"
                self.call_from_thread(log.write, f"     {mark} [dim]{escape(text)}[/]")

        try:
            answer, new_history = self.run_hook(
                prompt, self.history, verbose=False, ctx=CONTEXT, on_event=on_event,
            )
        except Exception as e:                   # 网络 / API / 工具异常都变成界面反馈
            self.call_from_thread(log.write, f"  [b red][出错][/] {escape(str(e))}\n")
            self.call_from_thread(self._finish_turn)
            return

        self.call_from_thread(self._apply_answer, answer, new_history, log)

    def _apply_answer(self, answer: str, new_history: list, log: RichLog) -> None:
        """主线程：落历史 → 打印回答 → 检查用量 → 恢复输入。"""
        self.history = list(new_history)
        log.write(f"[b yellow]xAgent：[/]{escape(answer)}\n")
        self._finish_turn()

    def _finish_turn(self) -> None:
        """一轮结束：刷新闸门、状态栏，恢复输入框。"""
        used = CONTEXT.used_tokens(self._messages())
        CONTEXT.update_blocked(used)             # 越过 70% 就挂闸门
        self.busy = False
        prompt_input = self.query_one("#prompt", Input)
        prompt_input.disabled = False
        prompt_input.focus()
        self._refresh_status()

    # ------------------------------------------------------------------ #
    # 上下文压缩
    # ------------------------------------------------------------------ #
    def _start_compact(self, log: RichLog) -> None:
        if not self.history:
            log.write("[dim]ℹ️ 当前会话还没有历史消息，不需要压缩。[/]")
            return
        self.busy = True
        self.query_one("#prompt", Input).disabled = True
        self._refresh_status()
        log.write(f"[b cyan]⚙️ 开始压缩上下文[/]（{len(self.history)} 条消息 → 归档 → "
                  f"LLM 摘要 → 替换历史；期间不执行工具、不处理新任务）")
        self._compact_worker(log)

    @work(thread=True, exclusive=True)
    def _compact_worker(self, log: RichLog) -> None:
        def progress(msg: str) -> None:
            self.call_from_thread(log.write, f"[dim]{escape(msg.strip())}[/]")

        before = cm.estimate_messages_tokens(self.history)
        try:
            new_history, info = compact_session(
                self.history, ctx=CONTEXT, verbose=True,
                printer=lambda m: progress(m),
            )
        except cm.CompactError as e:             # 归档失败 / 摘要为空：原历史不动
            self.call_from_thread(log.write, f"[b red]❌ 压缩失败[/]：{escape(str(e))}")
            self.call_from_thread(log.write, "[dim]   原有上下文完整保留，可再次输入 /compact 重试[/]\n")
        except Exception as e:                   # 网络 / API 异常
            self.call_from_thread(log.write, f"[b red]❌ 压缩失败[/]：{escape(str(e))}")
            self.call_from_thread(log.write, "[dim]   原有上下文完整保留，可再次输入 /compact 重试[/]\n")
        else:
            after = cm.estimate_messages_tokens(new_history)
            self.call_from_thread(self._apply_compact, new_history, info, before, after, log)
            return
        self.call_from_thread(self._finish_turn)

    def _apply_compact(self, new_history: list, info: dict,
                       before: int, after: int, log: RichLog) -> None:
        self.history = list(new_history)
        log.write(f"[b green]✅ 压缩完成[/]：{info['replaced']} 条 → 1 条摘要 ｜ "
                  f"Token 约 {cm.format_k(before)} → 约 {cm.format_k(after)}")
        log.write(f"[dim]   归档编号：{escape(info['id'])}[/]")
        log.write(f"[dim]   归档文件：{escape(str(info['path']))}[/]")
        log.write("[dim]   摘要末尾已追加归档说明；需要旧细节可让 Agent 调用 recallContext 检索[/]\n")
        self._finish_turn()

    # ------------------------------------------------------------------ #
    # 只读命令
    # ------------------------------------------------------------------ #
    def _show_context(self, log: RichLog) -> None:
        msgs = self._messages()
        used = CONTEXT.used_tokens(msgs)
        ratio = CONTEXT.ratio(used)
        archives = cm.list_archives(CONTEXT.archive_dir)
        log.write(
            f"[b]上下文[/] {cm.format_k(used)} / {cm.format_k(CONTEXT.window)}"
            f"{'（默认值，未识别到模型窗口）' if CONTEXT.window_is_default else ''} · "
            f"{ratio * 100:.1f}%（来源 {'API usage' if CONTEXT.api_source == 'api' else '字符估算'}）"
        )
        log.write(f"[dim]   阈值 {cm.WARN_RATIO * 100:.0f}% → "
                  f"{'已触发，需 /compact' if CONTEXT.blocked else '未触发'} ｜ "
                  f"历史 {len(self.history)} 条 ｜ 归档 {len(archives)} 个[/]")
        log.write(f"[dim]   归档目录：{escape(str(CONTEXT.archive_dir))}[/]")
        for p in archives[:5]:
            log.write(f"[dim]     - {escape(p.stem)}  ({p.stat().st_size / 1024:.1f} KB)[/]")
        if len(archives) > 5:
            log.write(f"[dim]     … 另有 {len(archives) - 5} 个[/]")
        log.write("")
        self._refresh_status()

    def _show_tools(self, log: RichLog) -> None:
        log.write(f"[b]共 {len(LOCAL_SCHEMAS) + len(MCP.tools)} 个工具[/]")
        for s in LOCAL_SCHEMAS:
            fn = s["function"]
            log.write(f"  [cyan]{escape(fn['name']):<24}[/] [dim]本地 ｜ "
                      f"{escape((fn.get('description') or '')[:60])}[/]")
        for t in MCP.tools.values():
            log.write(f"  [magenta]{escape(t.exposed):<24}[/] [dim]MCP:{escape(t.server)} ｜ "
                      f"{escape((t.schema.get('description') or '')[:60])}[/]")
        for name, reason in (MCP.failures or {}).items():
            log.write(f"  [b red]{escape(name)} 连接失败[/] [dim]{escape(reason)}[/]")
        log.write("")

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    def action_clear_chat(self) -> None:
        if self.busy:
            return
        self.history = []
        CONTEXT.reset_usage()
        log = self.query_one("#chatlog", RichLog)
        log.clear()
        log.write("[dim]—— 会话已清空，开始新对话 ——[/]\n")
        self._refresh_status()


if __name__ == "__main__":
    XAgentTUI().run()
