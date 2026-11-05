# -*- coding: utf-8 -*-
"""commands —— xAgent 斜杠命令注册表（TUI 补全面板 / /help / CLI 共用）。

每条命令 (名称, 别名元组, 一句话说明)。补全面板按输入前缀过滤，
/ help 文本和命令行版帮助也由这里生成，保证三处说明永远一致。
"""
from __future__ import annotations

# (命令, 别名, 说明)
COMMANDS: list[tuple[str, tuple, str]] = [
    ("/new",     (),            "新建会话（自动保存当前会话历史）"),
    ("/resume",  ("/sessions",), "打开历史会话面板，上下键选择、回车恢复、Esc 取消"),
    ("/save",    (),            "保存当前会话到 .agents/sessions/"),
    ("/quit",    ("/exit",),    "保存并退出 xAgent"),
    ("/compact", ("/compress",), "压缩上下文：先归档原文，再让 LLM 生成摘要替换历史"),
    ("/result",  ("/panel", "/last"), "重新打开上次压缩的对照面板（左原文 / 右摘要）"),
    ("/logs",    ("/log",),     "查看最近几次压缩记录（压缩了什么、摘要结构）"),
    ("/context", ("/status",),  "查看上下文用量、阈值状态与归档文件"),
    ("/history", (),            "查看当前会话的完整消息历史"),
    ("/tools",   (),            "查看当前可调用的全部工具（本地 + MCP）"),
    ("/mcp",     (),            "查看 MCP 服务器连接状态与各服务器的工具"),
    ("/skills",  (),            "查看已注册的技能清单"),
    ("/model",   (),            "查看当前模型与上下文窗口"),
    ("/config",  (),            "查看配置文件位置与关键参数"),
    ("/clear",   (),            "清空当前会话（等同 F2）"),
    ("/help",    ("/?",),       "显示本帮助"),
]


def primary_names() -> list[str]:
    """全部主命令名（不含别名），按注册顺序。"""
    return [c[0] for c in COMMANDS]


def all_names() -> list[str]:
    """主命令 + 别名，补全面板用。"""
    names: list[str] = []
    for name, aliases, _ in COMMANDS:
        names.append(name)
        names.extend(aliases)
    return names


def description_of(name: str) -> str:
    """命令（主名或别名）的一句话说明。"""
    low = name.lower()
    for name_, aliases, desc in COMMANDS:
        if low == name_ or low in aliases:
            return desc
    return ""


def complete_prefix(prefix: str) -> list[str]:
    """按输入前缀过滤出可补全的命令名（保持注册顺序）。"""
    low = prefix.lower()
    return [n for n in all_names() if n.startswith(low)]


def help_text() -> str:
    """渲染 /help 的文本（纯文本，CLI 与 TUI 通用）。"""
    lines = ["可用命令："]
    for name, _aliases, desc in COMMANDS:
        lines.append(f"  {name:<10} {desc}")
    lines.append("  （输入 / 会弹出命令补全面板：↑↓ 选择，Tab/回车补全，Esc 关闭）")
    return "\n".join(lines)
