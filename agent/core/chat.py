# -*- coding: utf-8 -*-
"""聊天核心层。

单一数据源原则：本模块**不复制**任何业务代码，直接转发引用原始文件
``llm_cli.py``（配置加载 + DashScope SSE 流式调用都在原件里）。
改原件，所有界面版本（TUI / 未来 Web / Desktop）自动跟随。

本模块额外提供 ``ChatService``——会话状态（历史记录）管理，
供各 UI 层使用；UI 层禁止绕过它直接调用原件的底层函数。
"""
import sys
from pathlib import Path

# 原始文件位于 agent 根目录（core/ 的上一级）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- 转发引用原件（公开给 UI 层的底层能力，均来自 llm_cli.py）----
import llm_cli  # noqa: E402
from llm_cli import ask_stream  # noqa: E402,F401

# 原件里叫 _load_config，这里补一个不含下划线的公开别名
load_config = llm_cli._load_config


class ChatService:
    """一次聊天会话：管理历史记录，把流式回复沉淀进历史。

    纯业务逻辑，零 UI 依赖——TUI / Web / Desktop 共用。
    """

    def __init__(self) -> None:
        self.history: list[dict] = []          # 与原件相同的 messages 结构

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
        if parts:
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": "".join(parts)})

    # ---------- 元信息 ----------
    @property
    def model(self) -> str:
        return load_config()[2]

    @property
    def base_url(self) -> str:
        return load_config()[0]

    def has_key(self) -> bool:
        return bool(load_config()[1])
