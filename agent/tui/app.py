# -*- coding: utf-8 -*-
"""大模型对话 · Textual TUI。

布局：顶部信息栏（模型名 / 轮数 / 上下文占用）+ 聊天记录区 + 输入框。
流式渲染：输入提交后开后台线程 worker，逐块把回复写进日志区，
界面在流式期间保持可滚动、可查看，不阻塞。

上下文管理：
    · 状态栏实时显示「上下文 已用k / 窗口k · 百分比」，超过 70% 变红并提示；
    · 达到 70% 后暂停接收普通消息，只接受 /compact，直到压缩成功；
    · /compact 先归档 .agents/context/<编号>.jsonl，再让 LLM 生成摘要替换历史。

快捷键：Enter 发送 ｜ F2 / ctrl+l 清空会话 ｜ ctrl+q 退出。
"""
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog, Static

from rich.markup import escape

from core import context as cm
from core.chat import ChatService


class ChatTUI(App):
    TITLE = "大模型对话"
    SUB_TITLE = "core + tui 分层架构 · Textual"

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

    BINDINGS = [
        ("f2", "clear_chat", "清空会话"),
        ("ctrl+l", "clear_chat", "清空会话"),
        ("ctrl+q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.service = ChatService()

    # ---------- 界面结构 ----------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="statusbar")
        yield RichLog(id="chatlog", highlight=False, markup=True, wrap=True)
        yield Input(placeholder="输入消息，Enter 发送（/compact 压缩上下文 ／ exit 退出 ／ F2 清空）", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status()
        log = self.query_one("#chatlog", RichLog)
        log.write("[b cyan]对话大语言模型[/]（记得之前聊过的内容）")
        log.write("[dim]Enter 发送 ｜ /compact 压缩上下文 ｜ /context 看用量 ｜ F2 清空会话 ｜ ctrl+q 退出[/]\n")
        self.query_one("#prompt", Input).focus()

    # ---------- 状态栏 ----------
    def _refresh_status(self) -> None:
        bar = self.query_one("#statusbar", Static)
        model = self.service.model
        turns = self.service.turns
        state = "就绪" if self.service.has_key() else "[b red]未配置 API Key[/]"
        ctx = self.service.context_status()
        tail = "（默认）" if ctx["is_default"] else ""
        blocks = int(round(ctx["ratio"] * 10))
        meter = "█" * blocks + "░" * (10 - blocks)
        warn = " [b red]← 请 /compact[/]" if ctx["blocked"] else ""
        text = (
            f"模型: {model} ｜ 轮数: {turns} ｜ "
            f"上下文 [{ctx['color']}]{ctx['used_k']}/{ctx['window_k']}{tail} · "
            f"{ctx['ratio'] * 100:.1f}% {meter}[/]{warn} ｜ {state}"
        )
        self.status_text = text              # 供自测断言（纯文本，含 markup）
        bar.update(text)

    # ---------- 发送与流式渲染 ----------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        if text.lower() in ("exit", "quit", "q"):
            self.exit()
            return
        log = self.query_one("#chatlog", RichLog)

        # ---- 命令 ----
        if text.startswith("/"):
            cmd = text.lower()
            if cmd in ("/compact", "/compress"):
                self._start_compact(log)
            elif cmd in ("/context", "/status"):
                self._show_context(log)
            elif cmd in ("/logs", "/log"):
                self._show_logs(log)
            elif cmd in ("/help", "/?"):
                self._show_help(log)
            else:
                log.write(f"[b red]未知命令[/]：{text}（输入 /help 查看可用命令）\n")
            return

        # ---- 闸门：达到 70% 只接受 /compact ----
        if self.service.blocked():
            pct = self.service.ratio() * 100
            log.write(f"[b red]⛔ 上下文已占用 {pct:.1f}%，已暂停处理新消息。"
                      f"[/]请先输入 [b cyan]/compact[/] 压缩上下文。\n")
            self._refresh_status()
            return

        prompt_input = self.query_one("#prompt", Input)
        prompt_input.disabled = True           # 流式期间禁用输入，防止并发轮次错乱
        log.write(f"[b green]你：[/]{text}")
        self._stream_reply_worker(text, log)

    # ---------- 上下文压缩 ----------
    def _start_compact(self, log: RichLog) -> None:
        prompt_input = self.query_one("#prompt", Input)
        prompt_input.disabled = True
        log.write("[b cyan]⚙️ 开始压缩上下文[/]（归档原始记录 → LLM 生成摘要 → 替换历史，"
                  "期间不处理新消息）")
        self._compact_worker(log)

    @work(thread=True, exclusive=True)
    def _compact_worker(self, log: RichLog) -> None:
        """后台线程执行压缩，进度用 call_from_thread 回主线程打印。"""
        def progress(msg: str) -> None:
            self.call_from_thread(log.write, f"[dim]{msg.strip()}[/]")

        try:
            info = self.service.compact(progress=progress)
        except Exception as e:                 # 失败保留原上下文，可重试
            self.call_from_thread(log.write, f"[b red]❌ 压缩失败[/]：{e}")
            self.call_from_thread(log.write, "[dim]原有上下文完整保留，可再次输入 /compact 重试[/]\n")
        else:
            self.call_from_thread(
                log.write,
                f"[b green]✅ 压缩完成[/]：{info['replaced']} 条消息 → 1 条摘要，"
                f"归档编号 [b]{info['id']}[/]",
            )
            self.call_from_thread(self._write_compact_block, log, info)
        finally:
            self.call_from_thread(self._finish_turn)

    def _write_compact_block(self, log: RichLog, info: dict) -> None:
        """压缩完成后打印「本次压缩了什么」明细。"""
        for line in cm.describe_block(info):
            raw = line.rstrip()
            indent = " " * (len(raw) - len(raw.lstrip()))
            body = raw.strip()
            if body.startswith("📦"):
                log.write(f"[b]{body}[/]")
                continue
            head, sep, rest = body.partition("  ")
            if sep and rest.strip() and len(head) <= 10 and not head[:1].isdigit():
                log.write(f"{indent}[b]{head}[/]  [dim]{rest.strip()}[/]")
            else:
                log.write(f"{indent}[dim]{body}[/]")
        log.write("[dim]   需要旧细节可让 Agent 调用 recallContext 检索；输入 /logs 查看历次记录[/]\n")

    def _show_context(self, log: RichLog) -> None:
        ctx = self.service.context_status()
        tail = "（默认值，未识别到模型窗口）" if ctx["is_default"] else ""
        log.write(
            f"[b]上下文[/] {ctx['used_k']} / {ctx['window_k']}{tail} · "
            f"{ctx['ratio'] * 100:.1f}%（来源 {ctx['source']}）｜ "
            f"历史 {len(self.service.history)} 条 ｜ 归档 {ctx['archives']} 个\n"
            f"[dim]归档目录：{self.service.ctx.archive_dir}[/]\n"
        )
        self._refresh_status()

    def _show_logs(self, log: RichLog) -> None:
        """查看最近几次压缩记录。"""
        log_path = self.service.ctx.archive_dir / cm.COMPACT_LOG_NAME
        text = cm.read_compact_log(log_path, 3)
        if not text:
            log.write("[dim]暂无压缩记录，执行一次 /compact 后会生成。[/]\n")
            return
        log.write(f"[b]最近几次压缩记录[/] [dim]（{escape(str(log_path))}）[/]")
        for line in text.splitlines():
            log.write(f"[dim]{escape(line)}[/]")
        log.write("")

    def _show_help(self, log: RichLog) -> None:
        log.write(
            "[b]可用命令[/]\n"
            "  [b cyan]/compact[/]  压缩上下文（先归档原文，再生成摘要替换历史）\n"
            "  [b cyan]/context[/]  查看上下文用量与归档\n"
            "  [b cyan]/logs[/]     查看最近几次压缩记录（压了哪些内容）\n"
            "  [b cyan]/help[/]     本帮助\n"
            "  [b cyan]exit[/]      退出（或 ctrl+q）\n"
        )

    @work(thread=True, exclusive=False)
    def _stream_reply_worker(self, prompt: str, log: RichLog) -> None:
        # 注意：worker 跑在后台线程，DOM 访问（query_one 等）必须经
        # call_from_thread 回到主线程执行，这里直接持有主线程传来的引用
        self.call_from_thread(log.write, "[b yellow]AI：[/]")
        got = False
        try:
            for piece in self.service.stream_reply(prompt):
                got = True
                self.call_from_thread(log.write, piece)
        except Exception as e:                 # 双保险：任何异常都变成界面反馈
            got = True
            self.call_from_thread(log.write, f"[b red][出错][/]{e}")
        if not got:
            self.call_from_thread(log.write, "[dim]（无内容返回）[/]")
        self.call_from_thread(log.write, "\n")
        self.call_from_thread(self._finish_turn)

    def _finish_turn(self) -> None:
        """一轮对话结束（主线程）：恢复输入框并刷新状态栏。"""
        prompt_input = self.query_one("#prompt", Input)
        prompt_input.disabled = False
        prompt_input.focus()
        self._refresh_status()

    # ---------- 动作 ----------
    def action_clear_chat(self) -> None:
        self.service.reset()
        log = self.query_one("#chatlog", RichLog)
        log.clear()
        log.write("[dim]—— 会话已清空，开始新对话 ——[/]\n")
        self._refresh_status()
