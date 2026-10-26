# -*- coding: utf-8 -*-
"""大模型对话 · Textual TUI。

布局：顶部信息栏（模型名 / 轮数）+ 聊天记录区 + 输入框。
流式渲染：输入提交后开后台线程 worker，逐块把回复写进日志区，
界面在流式期间保持可滚动、可查看，不阻塞。

快捷键：Enter 发送 ｜ F2 / ctrl+l 清空会话 ｜ ctrl+q 退出。
"""
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog, Static

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
        yield Input(placeholder="输入消息，Enter 发送（exit / F2 清空 / ctrl+q 退出）", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status()
        log = self.query_one("#chatlog", RichLog)
        log.write("[b cyan]对话大语言模型[/]（记得之前聊过的内容）")
        log.write("[dim]Enter 发送 ｜ F2 清空会话 ｜ ctrl+q 退出[/]\n")
        self.query_one("#prompt", Input).focus()

    # ---------- 状态栏 ----------
    def _refresh_status(self) -> None:
        bar = self.query_one("#statusbar", Static)
        model = self.service.model
        turns = self.service.turns
        state = "就绪" if self.service.has_key() else "[b red]未配置 API Key[/]"
        bar.update(f"模型: {model} ｜ 对话轮数: {turns} ｜ {state}")

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
        prompt_input = self.query_one("#prompt", Input)
        prompt_input.disabled = True           # 流式期间禁用输入，防止并发轮次错乱
        log.write(f"[b green]你：[/]{text}")
        self._stream_reply_worker(text, log)

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
