# -*- coding: utf-8 -*-
"""xAgent · Textual TUI（带边栏 / 斜杠命令补全 / 会话管理）。

和 `main.py` 的命令行版是同一套内核（xagent.py），界面结构：
    · 顶部状态栏：模型 / 轮数 / 工具数量 / 上下文 已用k / 窗口k · 百分比 · 占用条
    · 左侧边栏：MCP 服务器与各服务器可用工具（异步加载，加载完动态刷新）、技能清单
    · 中部聊天区：用户消息、工具调用（🔧）、工具返回（📤）、最终回答
    · 底部输入框：输入 / 弹出命令补全引导面板（↑↓ 选择，Tab/回车 补全，Esc 关闭）

斜杠命令：
    /new /resume /save /quit（/exit） /compact /result /logs /context
    /history /tools /mcp /skills /model /config /clear /help

会话管理（session_store.py）：
    · 每轮结束自动保存到 .agents/sessions/<会话ID>.json（config.ini 可关）；
    · /new 新建会话并自动保存当前会话；/resume 面板选择恢复；
    · 项目根有 AGENTS.md 时，新建会话把它注入为第一条消息（一次注入全程复用）。

启动：
    py tui_app.py          （或双击 xAgent对话.bat）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---- 配置自举：导入内核前保证 config.ini 存在（没有就生成 mock 并弹窗） ----
import app_config                                        # noqa: E402
_CONFIG_PATH, _CONFIG_CREATED = app_config.ensure_config(Path(__file__).resolve().parent.parent)
if _CONFIG_CREATED:
    from textual.app import App, ComposeResult           # noqa: E402
    from textual.containers import Vertical              # noqa: E402
    from textual.screen import ModalScreen               # noqa: E402
    from textual.widgets import Button, Static           # noqa: E402

    class _ConfigNoticeScreen(ModalScreen):
        BINDINGS = [("escape", "quit_app", "退出")]

        def compose(self) -> ComposeResult:
            with Vertical(id="notice-dialog"):
                yield Static("[b yellow]⚠️ 已生成示例配置文件[/]\n\n"
                             f"[b]{_CONFIG_PATH}[/]\n\n"
                             "当前是 mock 信息，还不能正常工作。\n"
                             "请打开该文件，至少把 [b][llm] api_key[/] 改成你自己的，\n"
                             "[b red]修改保存后重新启动 xAgent 才能正常工作。[/]",
                             id="notice-text")
                yield Button("我知道了，退出程序", id="notice-quit", variant="warning")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "notice-quit":
                self.app.exit()

        def action_quit_app(self) -> None:
            self.app.exit()

    class _ConfigNoticeApp(App):
        CSS = """
        #notice-dialog { width: 70%; height: auto; max-height: 70%;
                         border: thick $warning; background: $surface; padding: 1 2; }
        #notice-text { margin-bottom: 1; }
        """
        TITLE = "xAgent · 配置文件已生成"

        def compose(self) -> ComposeResult:
            yield _ConfigNoticeScreen()

        def on_mount(self) -> None:
            self.push_screen(_ConfigNoticeScreen())

    _ConfigNoticeApp().run()
    sys.exit(0)

from rich.markup import escape                              # noqa: E402
from textual import work                                  # noqa: E402
from textual.app import App, ComposeResult                # noqa: E402
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.screen import ModalScreen                    # noqa: E402
from textual.widgets import (Button, Footer, Header, Input,  # noqa: E402
                             OptionList, RichLog, Static)

import commands as slash                                  # noqa: E402
import context_manager as cm                              # noqa: E402
import session_store as store                             # noqa: E402
import xagent as xa                                       # noqa: E402
from xagent import (CONTEXT, LOCAL_SCHEMAS, MCP,          # noqa: E402
                    compact_session, run_agent, system_prompt)

HELP = "[b]" + slash.help_text().replace("\n", "[/]\n[b]") + "[/]"

CSS = """
#statusbar {
    height: 1;
    padding: 0 1;
    background: $panel;
    color: $text-muted;
}
#main { height: 1fr; }
#sidebar {
    width: 34;
    min-width: 24;
    border: round $primary;
    padding: 0 1;
}
#sidebar-scroll { height: 1fr; background: transparent; }
#sidebar-body { padding: 0; background: transparent; }
#chat-area { width: 1fr; height: 1fr; }
#chatlog {
    border: round $primary;
    padding: 0 1;
    height: 1fr;
}
#prompt {
    border: round $accent;
}

/* ---------- 斜杠命令补全引导面板 ---------- */
#palette {
    display: none;
    max-height: 14;
    border: round $accent;
    background: $surface;
    padding: 0;
}
#palette-title {
    height: 1;
    padding: 0 1;
    background: $panel;
    color: $text-muted;
}
#palette-list { height: auto; max-height: 12; background: transparent; }

/* ---------- 压缩结果浮动面板 ---------- */
CompactResultScreen {
    align: center middle;
    background: $background 70%;
}
#compact-dialog {
    width: 96%;
    height: 92%;
    border: thick $accent;
    background: $surface;
    padding: 0 1;
}
#compact-bar { height: 3; }
#compact-bar-title { width: 1fr; content-align: left middle; padding: 0 1; }
#compact-meta { height: auto; padding: 0 1 1 1; }
#compact-body { height: 1fr; }
.col { width: 1fr; height: 1fr; }
.col-title { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
#col-left { border: round $primary; }
#col-right { border: round $success; }
.col-log { height: 1fr; padding: 0 1; }
#compact-hint { height: 1; padding: 0 1; color: $text-muted; }

/* ---------- 会话恢复面板 ---------- */
ResumeScreen { align: center middle; background: $background 70%; }
#resume-dialog {
    width: 76%; max-width: 90; height: 70%;
    border: thick $secondary; background: $surface; padding: 0 1;
}
#resume-title { height: 1; padding: 0 1; content-align: left middle; }
#resume-list { height: 1fr; padding: 0 1; background: transparent; }
#resume-hint { height: 1; padding: 0 1; color: $text-muted; }

/* ---------- 配置提示 / 通用通知对话框 ---------- */
NoticeScreen { align: center middle; background: $background 70%; }
#notice-dialog {
    width: 64%; max-width: 72; height: auto; max-height: 80%;
    border: thick $warning; background: $surface; padding: 1 2;
}
#notice-text { margin-bottom: 1; }
"""


# --------------------------------------------------------------------------- #
# 压缩结果浮动面板（左原文 / 右摘要）
# --------------------------------------------------------------------------- #
class CompactResultScreen(ModalScreen):
    """压缩完成后的浮动面板：左侧压缩前原文，右侧压缩后结果。

    · 两栏各自独立滚动（↑↓ / PgUp / PgDn / 鼠标滚轮）；
    · 右栏是压缩后真正替换进历史的摘要正文 + 归档说明；
    · 右上角「✕ 关闭」按钮或 Esc 关闭，关闭后回到对话界面继续提问。
    """

    BINDINGS = [("escape", "close_panel", "关闭面板")]

    def __init__(self, info: dict, original_view: str,
                 before: int, after: int) -> None:
        super().__init__()
        self.info = info or {}
        self.original_view = original_view or "（没有可展示的历史消息）"
        self.before = int(before or 0)
        self.after = int(after or 0)

    # ---------------- 结构 ----------------
    def compose(self) -> ComposeResult:
        with Vertical(id="compact-dialog"):
            with Horizontal(id="compact-bar"):
                yield Static("[cyan]上下文压缩结果[/] [dim]· 压缩前原文 / 压缩后摘要对照[/]",
                             id="compact-bar-title")
                yield Button("✕ 关闭", id="compact-close", variant="error")
            yield Static(self._meta_text(), id="compact-meta")
            with Horizontal(id="compact-body"):
                with Vertical(classes="col", id="col-left"):
                    yield Static(self._left_title(), classes="col-title")
                    yield RichLog(id="compact-left", classes="col-log", min_width=20,
                                  markup=True, wrap=True, highlight=False,
                                  auto_scroll=False)
                with Vertical(classes="col", id="col-right"):
                    yield Static(self._right_title(), classes="col-title")
                    yield RichLog(id="compact-right", classes="col-log", min_width=20,
                                  markup=True, wrap=True, highlight=False,
                                  auto_scroll=False)
            yield Static("↑↓ / PgUp / PgDn 滚动　｜　Tab 切换左右　｜　"
                         "Esc 或点右上角「✕ 关闭」返回对话", id="compact-hint")

    def on_mount(self) -> None:
        self.call_after_refresh(self._fill_panes)

    def _fill_panes(self) -> None:
        left = self.query_one("#compact-left", RichLog)
        right = self.query_one("#compact-right", RichLog)
        self._fill(left, self.original_view, "cyan")
        self._fill(right, cm.render_summary_view(self.info), "green")
        for log in (left, right):                # 从第一行开始看，不要自动跳到末尾
            log.scroll_home(animate=False)
        left.focus()

    # ---------------- 文案 ----------------
    def _meta_text(self) -> str:
        info = self.info
        before = info.get("before") or {}
        roles = before.get("roles") or {}
        ratio = (self.after / self.before * 100) if self.before else 0
        return (
            f"[cyan]归档编号[/] {escape(str(info.get('id', '')))}　"
            f"[cyan]压缩时间[/] {escape(str(info.get('when', '')))}　"
            f"[cyan]模型[/] {escape(str(info.get('model', '')))}\n"
            f"[cyan]Token[/] [b yellow]{cm.format_k(self.before)} → {cm.format_k(self.after)}[/]"
            f"（占 {ratio:.0f}%）　｜　[cyan]消息[/] {info.get('replaced', 0)} 条"
            f"（u{roles.get('user', 0)}/a{roles.get('assistant', 0)}/t{roles.get('tool', 0)}）"
            f"　｜　[cyan]原文[/] {info.get('source_chars', 0):,} 字符 "
            f"≈ {cm.format_k(info.get('source_tokens', 0))} Tokens\n"
            f"[dim]归档文件：{escape(str(info.get('path', '')))}[/]"
        )

    def _left_title(self) -> str:
        return (f"[cyan]◀ 压缩前原文[/] [dim]· {self.info.get('replaced', 0)} 条 · "
                f"{len(self.original_view):,} 字符[/]")

    def _right_title(self) -> str:
        return (f"[green]压缩后结果 ▶[/] [dim]· 1 条摘要 · "
                f"{self.info.get('chars', 0):,} 字符[/]")

    # ---------------- 渲染 ----------------
    def _fill(self, log: RichLog, text: str, head_color: str) -> None:
        for line in text.splitlines():
            if line.startswith("▌"):
                log.write(f"[{head_color}]{escape(line)}[/]")
            elif line.startswith("→"):
                log.write(f"[yellow]{escape(line)}[/]")
            else:
                log.write(escape(line))

    # ---------------- 关闭 ----------------
    def action_close_panel(self) -> None:
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "compact-close":
            self.dismiss()


# --------------------------------------------------------------------------- #
# 历史会话面板：上下键选择、回车恢复、Esc 取消
# --------------------------------------------------------------------------- #
class ResumeScreen(ModalScreen):
    """历史会话列表。↑↓ 移动光标，回车恢复选中会话，Esc 取消。"""

    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, sessions: list[dict]) -> None:
        super().__init__()
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        with Vertical(id="resume-dialog"):
            yield Static("[b cyan]历史会话[/] [dim]· 共 "
                         f"{len(self.sessions)} 个[/]",
                         id="resume-title")
            yield OptionList(*self._items(), id="resume-list")
            yield Static("↑↓ 选择　｜　回车 恢复会话　｜　Esc 取消", id="resume-hint")

    def _items(self) -> list[str]:
        return [
            f"[b]{escape(s['title'])}[/]\n"
            f"[dim]{escape(s['id'])} · {s['turns']} 轮 · {s['messages']} 条 · "
            f"{escape(s['updated_at'])}[/]"
            for s in self.sessions
        ]

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opts = self.query_one("#resume-list", OptionList)
        idx = opts.highlighted
        if idx is None or not self.sessions:
            self.dismiss(None)
            return
        idx = min(idx, len(self.sessions) - 1)
        self.dismiss(self.sessions[idx]["id"])

    def action_cancel(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------- #
# 斜杠命令补全引导面板
# --------------------------------------------------------------------------- #
class CommandPalette(Vertical):
    """输入 / 时弹出的命令补全面板：↑↓ 选择、Tab/回车 补全、Esc 关闭。"""

    def __init__(self) -> None:
        super().__init__(id="palette")
        self._current: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("命令补全　↑↓ 选择　Tab/回车 补全　Esc 关闭", id="palette-title")
        yield OptionList(id="palette-list")

    # ---- 显示 / 隐藏 ----
    def update_for(self, value: str) -> bool:
        """按输入过滤命令并刷新列表；返回面板是否应显示。"""
        text = value.strip()
        # 注意空格判断用原始输入：补全完成后值形如 "/resume "，面板应保持收起
        if (not text.startswith("/") or " " in value or len(text) > 20):
            self.hide_palette()
            return False
        matches = slash.complete_prefix(text)
        if not matches:
            self.hide_palette()
            return False
        self._current = matches
        opts = self.query_one("#palette-list", OptionList)
        opts.clear_options()
        for name in matches:
            # 选中项用 self._current[highlighted] 定位，无需给 Option 挂 id；
            # OptionList 的 prompt 直接用字符串（Textual 8 不接受 Widget）。
            opts.add_option(
                f"[cyan]{escape(name):<14}[/][dim]{escape(slash.description_of(name))}[/]"
            )
        opts.highlighted = 0
        self.display = True
        self.add_class("-visible")
        return True

    def hide_palette(self) -> None:
        self.display = False
        self.remove_class("-visible")
        self._current = []

    @property
    def visible(self) -> bool:
        return self.display

    # ---- 键盘导航（由 PromptInput 转发） ----
    def move(self, delta: int) -> None:
        opts = self.query_one("#palette-list", OptionList)
        n = opts.option_count
        if not n:
            return
        cur = opts.highlighted or 0
        opts.highlighted = (cur + delta) % n

    def current_name(self) -> str | None:
        if not self._current:
            return None
        opts = self.query_one("#palette-list", OptionList)
        idx = opts.highlighted or 0
        idx = min(idx, len(self._current) - 1)
        return self._current[idx]


class PromptInput(Input):
    """带补全导航的输入框：面板可见时 ↑↓/Tab/回车/Esc 先交给面板处理。"""

    palette: CommandPalette | None = None

    async def _on_key(self, event) -> None:   # textual.events.Key
        pal = self.palette
        if pal is None or not pal.visible:
            return                            # 面板没显示：走 Input 默认行为
        if event.key == "down":
            event.stop()
            event.prevent_default()
            pal.move(1)
        elif event.key == "up":
            event.stop()
            event.prevent_default()
            pal.move(-1)
        elif event.key in ("tab", "enter"):
            event.stop()
            event.prevent_default()
            name = pal.current_name()
            if name:
                pal.hide_palette()
                self.value = name + " "
                self.cursor_position = len(self.value)
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            pal.hide_palette()


# --------------------------------------------------------------------------- #
# 通用通知对话框（/config 里查看 mock 状态等场景复用）
# --------------------------------------------------------------------------- #
class NoticeScreen(ModalScreen):
    """简单通知：Esc / 按钮关闭。"""

    BINDINGS = [("escape", "close", "关闭")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="notice-dialog"):
            yield Static(f"[b yellow]{escape(self._title)}[/]\n\n"
                         f"{escape(self._body)}", id="notice-text")
            yield Button("关闭", id="notice-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "notice-close":
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class XAgentTUI(App):
    """xAgent 的全屏界面：边栏 + 工具调用过程 + 上下文状态栏 + 会话管理。"""

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
        # ---- 会话初始化：AGENTS.md 一次注入，全程复用 ----
        self.history, agents_event = xa.new_session()
        self.pending_events: list[dict] = [agents_event] if agents_event else []
        self.session_id = store.new_session_id()
        self.busy = False             # 正在等 LLM / 跑工具 / 压缩
        self.status_text = ""         # 供自测断言
        self.sidebar_text = ""        # 边栏内容快照（供自测断言）
        self.run_hook = run_agent     # 自测时可替换为假实现
        self.last_compact_view = None  # 最近一次压缩的 (info, 原文, before, after)

    # ------------------------------------------------------------------ #
    # 界面结构
    # ------------------------------------------------------------------ #
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="statusbar")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("[b]📡 MCP 服务器[/]", id="sidebar-title")
                with VerticalScroll(id="sidebar-scroll"):
                    yield Static("⏳ 正在连接 MCP 服务器…", id="sidebar-body")
            with Vertical(id="chat-area"):
                yield RichLog(id="chatlog", highlight=False, markup=True, wrap=True)
                yield CommandPalette()
                yield PromptInput(
                    placeholder="输入消息，/ 弹出命令补全 ／ /help 帮助 ／ F2 清空",
                    id="prompt",
                )
        yield Footer()

    def on_mount(self) -> None:
        # 输入框 ←→ 补全面板 互相认识一下
        self.query_one("#prompt", PromptInput).palette = \
            self.query_one("#palette", CommandPalette)
        log = self.query_one("#chatlog", RichLog)
        log.write("[b cyan]xAgent[/]（可调用本地工具、技能与 MCP 远程工具）")
        log.write("[dim]MCP 服务器正在后台连接，连接完成后左侧边栏会自动刷新；"
                  "期间本地工具照常可用。[/]")
        if self.history:                     # AGENTS.md 已注入
            log.write(f"[dim]已从项目根注入 [b]AGENTS.md[/] 项目说明"
                      f"（一次注入，全程复用）。[/]")
        log.write(f"[dim]会话编号：{self.session_id}（每轮结束自动保存）[/]")
        log.write("[dim]输入 / 查看命令补全 ｜ /resume 恢复历史会话 ｜ ctrl+q 退出[/]\n")
        self._refresh_status()
        self._refresh_sidebar()
        self.query_one("#prompt", Input).focus()
        # ---- MCP 异步加载：界面已就绪，后台连接，完成后动态刷新边栏 ----
        if MCP.loaded:
            self._on_mcp_loaded()
        else:
            xa.load_mcp_async(on_done=self._mcp_done_cb)

    def _mcp_done_cb(self, registry) -> None:
        """MCP 后台加载完成（工作线程里调用）→ 回主线程刷新界面。"""
        try:
            self.call_from_thread(self._on_mcp_loaded)
        except Exception:
            pass

    def _on_mcp_loaded(self) -> None:
        log = self.query_one("#chatlog", RichLog)
        n_tools, n_fail = len(MCP.tools), len(MCP.failures)
        if n_fail:
            log.write(f"[yellow]📡 MCP 加载完成[/]：{len(MCP.clients)} 个服务器 · "
                      f"{n_tools} 个工具 · {n_fail} 个连接失败（详见 /mcp）[/]")
        else:
            log.write(f"[green]📡 MCP 加载完成[/]：{len(MCP.clients)} 个服务器 · "
                      f"{n_tools} 个工具，已加入可用工具清单。[/]")
        self._refresh_sidebar()
        self._refresh_status()

    def on_screen_resume(self) -> None:
        """浮动面板关闭后回到对话界面：重新聚焦输入框。"""
        try:
            prompt_input = self.query_one("#prompt", Input)
        except Exception:                        # 界面尚未构建完
            return
        if not self.busy:
            prompt_input.disabled = False
            prompt_input.focus()

    # ------------------------------------------------------------------ #
    # 边栏（MCP 服务器 + 工具 + 技能）
    # ------------------------------------------------------------------ #
    def _refresh_sidebar(self) -> None:
        lines: list[str] = ["[b]📡 MCP 服务器[/]"]
        if not MCP.loaded:
            lines.append("[yellow]⏳ 正在连接…[/]")
        else:
            if not MCP.clients and not MCP.failures:
                lines.append("[dim]未配置（.mcp.json 不存在或为空）[/]")
            for name, cnt in MCP.server_tools.items():
                lines.append(f"[green]✓[/] [b]{escape(name)}[/] [dim]· {cnt} 工具[/]")
                for t in MCP.tools.values():
                    if t.server == name:
                        lines.append(f"  [magenta]· {escape(t.exposed)}[/]")
            for name, reason in (MCP.failures or {}).items():
                lines.append(f"[red]✗[/] [b]{escape(name)}[/]")
                lines.append(f"  [dim]{escape(reason[:40])}[/]")
        lines.append("")
        lines.append(f"[b]🧰 本地工具[/] [dim]{len(LOCAL_SCHEMAS)} 个[/]")
        lines.append("")
        lines.append("[b]🧩 技能[/]")
        skills = SKILLS_ALL()
        if skills:
            for s in skills:
                lines.append(f"  [cyan]· {escape(s)}[/]")
        else:
            lines.append("[dim]（无，放 .agents/skills/ 下自动发现）[/]")
        body = self.query_one("#sidebar-body", Static)
        body.update("\n".join(lines))
        self.sidebar_text = "\n".join(lines)   # 供测试断言
        try:
            self.query_one("#sidebar-scroll", VerticalScroll).scroll_home(animate=False)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 状态栏
    # ------------------------------------------------------------------ #
    def _messages(self) -> list:
        """状态栏要计量的完整上下文：System Prompt + 历史（含工具消息）。"""
        return [{"role": "system", "content": system_prompt()}] + list(self.history)

    def _turns(self) -> int:
        """轮数 = 用户提问条数（压缩摘要 / AGENTS.md 注入消息不计入）。"""
        return sum(
            1 for m in self.history
            if m.get("role") == "user"
            and not str(m.get("content") or "").startswith(
                (store.SUMMARY_HEADER_MARK, store.AGENTS_MD_HEADER))
        )

    def _refresh_status(self) -> None:
        used = CONTEXT.used_tokens(self._messages())
        ratio = CONTEXT.ratio(used)
        color = ("green" if ratio < 0.5 else
                 ("yellow" if ratio < CONTEXT.warn_ratio else "red"))
        blocks = max(0, min(10, int(round(ratio * 10))))
        meter = "█" * blocks + "░" * (10 - blocks)
        tail = "（默认）" if CONTEXT.window_is_default else ""
        mcp_state = ("加载中…" if not MCP.loaded else f"{len(MCP.tools)}")
        local_n, mcp_n = len(LOCAL_SCHEMAS), len(MCP.tools)
        if self.busy:
            state = "[b yellow]运行中…[/]"
        elif CONTEXT.blocked:
            state = "[b red]← 请 /compact[/]"
        else:
            state = "就绪"
        text = (
            f"模型: {CONTEXT.model} ｜ 轮数: {self._turns()} ｜ "
            f"工具: {local_n + mcp_n}（本地 {local_n} / MCP {mcp_state}） ｜ "
            f"上下文 [{color}]{cm.format_k(used)}/{cm.format_k(CONTEXT.window)}{tail} · "
            f"{ratio * 100:.1f}% {meter}[/] ｜ {state}"
        )
        self.status_text = text
        self.query_one("#statusbar", Static).update(text)

    # ------------------------------------------------------------------ #
    # 输入处理
    # ------------------------------------------------------------------ #
    def on_input_changed(self, event: Input.Changed) -> None:
        """输入变化 → 刷新命令补全面板（输入 / 时弹出引导）。"""
        if event.input.id != "prompt":
            return
        pal = self.query_one("#palette", CommandPalette)
        pal.update_for(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.query_one("#palette", CommandPalette).hide_palette()
        log = self.query_one("#chatlog", RichLog)

        if text.lower() in ("exit", "quit", "q", "/exit", "/quit"):
            self._do_quit(log)
            return
        if self.busy:                            # 上一轮没结束，避免并发
            log.write("[b red]⏳ 正在执行中，请稍候…[/]")
            return

        if text.startswith("/"):
            self._dispatch_command(text.lower(), text, log)
            return

        if CONTEXT.blocked:                      # 阈值闸门：只接受 /compact
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
    # 斜杠命令分发
    # ------------------------------------------------------------------ #
    def _dispatch_command(self, cmd: str, raw: str, log: RichLog) -> None:
        if cmd in ("/compact", "/compress"):
            self._start_compact(log)
        elif cmd in ("/context", "/status"):
            self._show_context(log)
        elif cmd == "/tools":
            self._show_tools(log)
        elif cmd in ("/logs", "/log"):
            self._show_logs(log)
        elif cmd in ("/result", "/panel", "/last"):
            self._show_compact_panel(log)
        elif cmd == "/new":
            self._cmd_new(log)
        elif cmd in ("/resume", "/sessions"):
            self._cmd_resume(log)
        elif cmd == "/save":
            self._cmd_save(log)
        elif cmd in ("/quit", "/exit"):
            self._do_quit(log)
        elif cmd == "/history":
            self._show_history(log)
        elif cmd == "/mcp":
            self._show_mcp(log)
        elif cmd == "/skills":
            self._show_skills(log)
        elif cmd == "/model":
            self._show_model(log)
        elif cmd == "/config":
            self._show_config(log)
        elif cmd == "/clear":
            self.action_clear_chat()
        elif cmd in ("/help", "/?"):
            log.write(HELP)
        else:
            log.write(f"[b red]未知命令[/]：{escape(raw)}"
                      f"（输入 / 从补全面板选择，或 /help 查看全部命令）")

    # ---- /new：自动保存当前会话并新建 ----
    def _cmd_new(self, log: RichLog) -> None:
        saved_note = ""
        if self.history:
            meta = self._save_session()
            saved_note = (f"[green]💾 已保存当前会话[/] [dim]{escape(meta['id'])} → "
                          f"{escape(str(meta.get('path', '') or ''))}[/]")
        self.history, agents_event = xa.new_session()
        self.pending_events = [agents_event] if agents_event else []
        self.session_id = store.new_session_id()
        CONTEXT.reset_usage()
        chat = self.query_one("#chatlog", RichLog)
        chat.clear()                          # 先清屏，再写提示，避免被自己清掉
        chat.write(f"[b cyan]—— 新会话 {self.session_id} ——[/]")
        if saved_note:
            chat.write(saved_note)
        if agents_event:
            chat.write("[dim]已注入项目根 AGENTS.md（一次注入，全程复用）。[/]")
        chat.write("")
        self._refresh_status()

    # ---- /resume：历史会话面板 ----
    def _cmd_resume(self, log: RichLog) -> None:
        sessions = store.list_sessions(xa.SKILLS.project_root, xa.SESSIONS_SUB)
        if not sessions:
            log.write("[dim]暂无历史会话（.agents/sessions/ 为空）。[/]\n")
            return
        self.push_screen(ResumeScreen(sessions), self._resume_selected)

    def _resume_selected(self, session_id: str | None) -> None:
        if not session_id:
            return
        log = self.query_one("#chatlog", RichLog)
        try:
            history, meta = store.load_session(
                xa.SKILLS.project_root, session_id, xa.SESSIONS_SUB)
        except (OSError, ValueError) as e:
            log.write(f"[b red]恢复失败[/]：{escape(str(e))}")
            return
        # 恢复前把当前会话先存一份，避免丢历史
        if self.history:
            self._save_session()
        self.history = history
        self.session_id = meta.get("id") or session_id
        self.pending_events = []                 # 事件已随会话持久化过
        CONTEXT.reset_usage()
        chat = self.query_one("#chatlog", RichLog)
        chat.clear()
        chat.write(f"[b cyan]—— 已恢复会话 {escape(self.session_id)} ——[/]")
        chat.write(f"[dim]标题：{escape(meta.get('title', ''))} · "
                   f"{meta.get('turns', 0)} 轮 · {len(history)} 条消息[/]")
        shown = 0
        for m in history:                        # 回放可见消息（工具消息折叠）
            role = m.get("role")
            if role == "user":
                text = str(m.get("content") or "")
                tag = "[dim]（注入）[/]" if text.startswith(store.AGENTS_MD_HEADER) else ""
                chat.write(f"[b green]你：[/]{escape(text[:200])}{tag}")
                shown += 1
            elif role == "assistant" and m.get("content"):
                chat.write(f"[b yellow]xAgent：[/]{escape(str(m['content'])[:200])}")
                shown += 1
            elif role == "assistant" and m.get("tool_calls"):
                chat.write("[dim]·（工具调用轮）[/]")
        if not shown:
            chat.write("[dim]（该会话没有可见消息）[/]")
        chat.write("")
        self._refresh_status()

    # ---- /save：手动保存当前会话 ----
    def _cmd_save(self, log: RichLog) -> None:
        if not self.history:
            log.write("[dim]当前会话为空，没有可保存的内容。[/]")
            return
        meta = self._save_session()
        log.write(f"[green]💾 会话已保存[/]：{escape(meta['title'])}")
        log.write(f"[dim]   编号 {escape(meta['id'])} · {meta['turns']} 轮 · "
                  f"{meta['messages']} 条消息[/]")
        log.write(f"[dim]   文件 {escape(str(meta.get('path', '')))}[/]\n")

    # ---- /quit：保存并退出 ----
    def _do_quit(self, log: RichLog) -> None:
        if self.history:
            try:
                self._save_session()
            except Exception:
                pass
        self.exit()

    # ---- 会话保存（自动 + 手动共用） ----
    def _save_session(self) -> dict:
        meta = store.save_session(
            xa.SKILLS.project_root, self.history,
            session_id=self.session_id, sub=xa.SESSIONS_SUB,
            model=CONTEXT.model, events=self.pending_events or None)
        self.pending_events = []                 # 事件只记录一次
        return meta

    def _autosave(self) -> None:
        if not xa.CFG.autosave:
            return
        if not store.count_turns(self.history):
            return
        try:
            self._save_session()
        except Exception:
            pass                                 # 自动保存失败不打断对话

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
        self._autosave()
        self._finish_turn()

    def _finish_turn(self) -> None:
        """一轮结束：刷新闸门、状态栏，恢复输入框。"""
        used = CONTEXT.used_tokens(self._messages())
        CONTEXT.update_blocked(used)             # 越过阈值就挂闸门
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
        original_view = cm.render_history_view(self.history)   # 面板左侧用的原文快照
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
            self.call_from_thread(self._apply_compact, new_history, info,
                                  before, after, log, original_view)
            return
        self.call_from_thread(self._finish_turn)

    def _apply_compact(self, new_history: list, info: dict, before: int, after: int,
                       log: RichLog, original_view: str) -> None:
        self.history = list(new_history)
        log.write(f"[b green]✅ 压缩完成[/]：{info['replaced']} 条 → 1 条摘要 ｜ "
                  f"Token 约 {cm.format_k(before)} → 约 {cm.format_k(after)}")
        log.write(f"[dim]   归档编号：{escape(info['id'])}[/]")
        log.write(f"[dim]   归档文件：{escape(str(info['path']))}[/]")
        log.write("[dim]   摘要末尾已追加归档说明；需要旧细节可让 Agent 调用 recallContext 检索[/]")
        # 「本次压缩了什么」明细：条数/角色分布/涉及工具/用户诉求/摘要结构/体积
        for line in cm.describe_block(info):
            raw = line.rstrip()
            indent = " " * (len(raw) - len(raw.lstrip()))
            body = raw.strip()
            if body.startswith("📦"):
                log.write(f"[b]{escape(body)}[/]")
                continue
            head, sep, rest = body.partition("  ")
            if sep and rest.strip() and len(head) <= 10 and not head[:1].isdigit():
                log.write(f"{indent}[b]{escape(head)}[/]  [dim]{escape(rest.strip())}[/]")
            else:
                log.write(f"{indent}[dim]{escape(body)}[/]")
        log.write("[dim]   输入 /logs 可查看历次压缩记录，/result 可重新打开对照面板[/]\n")
        self._autosave()
        self._finish_turn()
        # 压缩完成 → 弹出浮动面板：左原文 / 右摘要，可滚动、可关闭
        self.last_compact_view = (info, original_view, before, after)
        self.push_screen(CompactResultScreen(info, original_view, before, after))

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
        log.write(f"[dim]   阈值 {CONTEXT.warn_ratio * 100:.0f}% → "
                  f"{'已触发，需 /compact' if CONTEXT.blocked else '未触发'} ｜ "
                  f"历史 {len(self.history)} 条 ｜ 归档 {len(archives)} 个[/]")
        log.write(f"[dim]   归档目录：{escape(str(CONTEXT.archive_dir))}[/]")
        for p in archives[:5]:
            log.write(f"[dim]     - {escape(p.stem)}  ({p.stat().st_size / 1024:.1f} KB)[/]")
        if len(archives) > 5:
            log.write(f"[dim]     … 另有 {len(archives) - 5} 个[/]")
        log.write("")
        self._refresh_status()

    def _show_compact_panel(self, log: RichLog) -> None:
        """重新打开最近一次压缩的对照面板（左侧原文 / 右侧摘要）。"""
        if not self.last_compact_view:
            log.write("[dim]暂无压缩记录，执行一次 /compact 后可查看对照面板。[/]\n")
            return
        info, original_view, before, after = self.last_compact_view
        self.push_screen(CompactResultScreen(info, original_view, before, after))

    def _show_logs(self, log: RichLog) -> None:
        """查看最近几次压缩日志：每次压了哪些内容、摘要结构、归档编号。"""
        log_path = CONTEXT.archive_dir / cm.COMPACT_LOG_NAME
        text = cm.read_compact_log(log_path, 3)
        if not text:
            log.write("[dim]暂无压缩记录，执行一次 /compact 后会生成。[/]")
            log.write(f"[dim]   日志文件：{escape(str(log_path))}[/]\n")
            return
        log.write(f"[b]最近几次压缩记录[/] [dim]（{escape(str(log_path))}）[/]")
        for line in text.splitlines():
            log.write(f"[dim]{escape(line)}[/]")
        log.write("")

    def _show_tools(self, log: RichLog) -> None:
        schemas = xa.tool_schemas()
        log.write(f"[b]共 {len(schemas)} 个工具[/]")
        for s in LOCAL_SCHEMAS:
            fn = s["function"]
            log.write(f"  [cyan]{escape(fn['name']):<24}[/] [dim]本地 ｜ "
                      f"{escape((fn.get('description') or '')[:60])}[/]")
        for t in MCP.tools.values():
            log.write(f"  [magenta]{escape(t.exposed):<24}[/] [dim]MCP:{escape(t.server)} ｜ "
                      f"{escape((t.schema.get('description') or '')[:60])}[/]")
        if not MCP.loaded:
            log.write("[yellow]  （MCP 还在后台加载，加载完成后会自动补充远程工具）[/]")
        for name, reason in (MCP.failures or {}).items():
            log.write(f"  [b red]{escape(name)} 连接失败[/] [dim]{escape(reason)}[/]")
        log.write("")

    def _show_mcp(self, log: RichLog) -> None:
        log.write(f"[b]MCP 服务器[/] [dim]（配置：{escape(str(MCP.config_path))}）[/]")
        if not MCP.loaded:
            log.write("[yellow]  ⏳ 正在后台连接，完成后边栏与 /tools 自动更新。[/]\n")
            return
        log.write(MCP.summary())
        for name, cnt in MCP.server_tools.items():
            tools = [t.exposed for t in MCP.tools.values() if t.server == name]
            log.write(f"  [b]{escape(name)}[/] 的工具：[magenta]{escape(', '.join(tools))}[/]")
        log.write("")

    def _show_skills(self, log: RichLog) -> None:
        log.write("[b]技能清单[/]")
        from xagent import SKILLS
        log.write(SKILLS.summary() or "[dim]（无）[/]")
        log.write("")

    def _show_history(self, log: RichLog) -> None:
        """查看当前会话完整历史（含注入消息与工具调用轨迹）。"""
        if not self.history:
            log.write("[dim]当前会话还没有历史消息。[/]\n")
            return
        log.write(f"[b]当前会话历史[/] [dim]· {len(self.history)} 条 · "
                  f"会话编号 {escape(self.session_id)}[/]")
        view = cm.render_history_view(self.history)
        for line in view.splitlines():
            if line.startswith("▌"):
                log.write(f"[cyan]{escape(line)}[/]")
            else:
                log.write(escape(line))
        log.write("")

    def _show_model(self, log: RichLog) -> None:
        log.write(f"[b]模型[/] {escape(CONTEXT.model)}")
        log.write(f"[dim]   上下文窗口 {cm.format_k(CONTEXT.window)}"
                  f"{'（默认值）' if CONTEXT.window_is_default else ''} ｜ "
                  f"告警阈值 {CONTEXT.warn_ratio * 100:.0f}%[/]")
        log.write(f"[dim]   API 地址 {escape(xa.CFG.base_url)}[/]\n")

    def _show_config(self, log: RichLog) -> None:
        cfg = xa.CFG
        log.write(f"[b]配置文件[/] {escape(str(cfg.config_path))}"
                  + ("　[red]（示例配置，请修改 api_key 后重启）[/]" if cfg.is_mock else ""))
        log.write(f"[dim]   base_url={escape(cfg.base_url)} ｜ model={escape(cfg.model)} ｜ "
                  f"timeout={cfg.timeout}s ｜ max_rounds={cfg.max_rounds}[/]")
        log.write(f"[dim]   warn_ratio={cfg.warn_ratio} ｜ default_window="
                  f"{cfg.default_window} ｜ sessions_dir={escape(cfg.sessions_dir)} ｜ "
                  f"autosave={'开' if cfg.autosave else '关'}[/]\n")

    # ------------------------------------------------------------------ #
    # 动作
    # ------------------------------------------------------------------ #
    def action_clear_chat(self) -> None:
        if self.busy:
            return
        self.history = []
        self.pending_events = []
        CONTEXT.reset_usage()
        log = self.query_one("#chatlog", RichLog)
        log.clear()
        log.write("[dim]—— 会话已清空，开始新对话 ——[/]\n")
        self._refresh_status()


def SKILLS_ALL() -> list[str]:
    """技能名列表（边栏用）。"""
    from xagent import SKILLS
    return sorted(s.name for s in SKILLS.skills.values()) if SKILLS.skills else []


if __name__ == "__main__":
    XAgentTUI().run()
