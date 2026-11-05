# -*- coding: utf-8 -*-
"""聊天核心层。

单一数据源原则：本模块**不复制**任何业务代码，直接转发引用原始文件
``llm_cli.py``（配置加载 + DashScope SSE 流式调用都在原件里）。
改原件，所有界面版本（TUI / 未来 Web / Desktop）自动跟随。

本模块额外提供 ``ChatService``——会话状态（历史记录）管理，
供各 UI 层使用；UI 层禁止绕过它直接调用原件的底层函数。
"""
import json
import sys
import urllib.request
from pathlib import Path

# 原始文件位于 agent 根目录（core/ 的上一级）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- 转发引用原件（公开给 UI 层的底层能力，均来自 llm_cli.py）----
import llm_cli  # noqa: E402
from llm_cli import ask_stream  # noqa: E402,F401

# 上下文压缩（逻辑在 xagent/context_manager.py，这里只做适配）
from core.context import (CompactError, ContextManager,  # noqa: E402
                          estimate_messages_tokens, format_k, ratio_color)

# 原件里叫 _load_config，这里补一个不含下划线的公开别名
load_config = llm_cli._load_config

# 摘要生成比较慢，单独给一个更宽松的超时（秒）
SUMMARY_TIMEOUT = 300


class ChatService:
    """一次聊天会话：管理历史记录，把流式回复沉淀进历史。

    纯业务逻辑，零 UI 依赖——TUI / Web / Desktop 共用。
    """

    def __init__(self) -> None:
        self.history: list[dict] = []          # 与原件相同的 messages 结构
        # 上下文计量 / 归档 / 压缩（项目本地 .agents/context/）
        self.ctx = ContextManager(project_root=_ROOT, model=self.model)

    # ---------- 会话状态 ----------
    @property
    def turns(self) -> int:
        """已完成的对话轮数。"""
        return len(self.history) // 2

    def reset(self) -> None:
        """清空聊天记录，开始新会话。"""
        self.history.clear()

    # ---------- 核心能力 ----------
    def stream_reply(self, prompt: str):
        """发送用户输入，逐块产出模型回复；回复完整后存入历史。

        生成器：UI 层 for 循环消费即可实现流式渲染。
        请求失败（HTTP 错误 / 无 Key）时不抛异常，产出一条
        以 "[出错]" 开头的文本，保证界面始终有反馈。
        """
        parts: list[str] = []
        try:
            for piece in ask_stream(prompt, self.history):
                parts.append(piece)
                yield piece
        except SystemExit as e:                # ask_stream 用 sys.exit 报错
            yield f"[出错] {e}"
            return
        except Exception as e:                 # 网络异常/超时等，不让异常炸掉界面线程
            yield f"[出错] 请求失败：{e}"
            return
        if parts:
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": "".join(parts)})

    # ---------- 上下文计量与压缩 ----------
    def used_tokens(self) -> int:
        """当前上下文的 Token 占用（历史消息；本界面没有 system prompt）。"""
        return self.ctx.used_tokens(self.history)

    def ratio(self) -> float:
        return self.ctx.ratio(self.used_tokens())

    def blocked(self) -> bool:
        """是否已到 70% 阈值：到达后应暂停接收普通输入，只允许 /compact。"""
        return self.ctx.update_blocked(self.used_tokens())

    def context_status(self) -> dict:
        used = self.used_tokens()
        self.ctx.update_blocked(used)          # 顺带同步闸门状态，状态栏才不会滞后
        return {
            "used": used,
            "used_k": format_k(used),
            "window": self.ctx.window,
            "window_k": format_k(self.ctx.window),
            "is_default": self.ctx.window_is_default,
            "ratio": self.ctx.ratio(used),
            "color": ratio_color(self.ctx.ratio(used)),
            "source": self.ctx.api_source,
            "blocked": self.ctx.blocked,
            "archives": len(list(self.ctx.archive_dir.glob("*.jsonl"))) if self.ctx.archive_dir.is_dir() else 0,
        }

    def replace_history(self, new_history: list) -> None:
        self.history[:] = list(new_history)

    def complete(self, system_prompt: str, user_content: str, max_tokens: int = 6000) -> str:
        """纯文本补全（非流式、不带历史）：只给上下文压缩用。

        刻意不复用 ask_stream——压缩必须是一次性的、确定的请求，
        不能边生成边往历史里写，也不能带工具定义。
        """
        base_url, key, model = load_config()
        if not key:
            raise RuntimeError("未配置 API Key，无法生成摘要")
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_content}],
            "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        )
        with urllib.request.urlopen(req, timeout=SUMMARY_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"].get("content") or ""

    def compact(self, progress=None) -> dict:
        """执行一次上下文压缩：归档原始记录 → LLM 生成摘要 → 替换历史。

        失败时抛 CompactError，且不会改动 self.history。
        """
        if not self.history:
            raise CompactError("当前会话还没有可压缩的历史消息。")
        printer = progress or (lambda *_: None)

        def chat(system_prompt: str, user_content: str, max_tokens: int = 6000) -> str:
            return self.complete(system_prompt, user_content, max_tokens)

        new_history, info = self.ctx.compact(self.history, chat, verbose=True, printer=printer)
        self.replace_history(new_history)      # 只有摘要生成成功才替换
        return info

    # ---------- 元信息 ----------
    @property
    def model(self) -> str:
        return load_config()[2]

    @property
    def base_url(self) -> str:
        return load_config()[0]

    def has_key(self) -> bool:
        return bool(load_config()[1])
