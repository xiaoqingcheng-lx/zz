# -*- coding: utf-8 -*-
"""上下文压缩能力的适配层。

单一数据源原则：压缩逻辑只写一份，放在 ``agent/xagent/context_manager.py``，
这里按**文件路径**动态加载它，不复制代码、也不往 sys.path 里塞目录
（避免 xagent 目录下的 main.py / skills.py 等把本项目的同名模块顶掉）。

对外只暴露 UI 层需要的东西：ContextManager、CompactError、几个格式化函数。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "xagent" / "context_manager.py"

if not _SRC.is_file():
    raise ImportError(f"找不到上下文压缩模块：{_SRC}")

_spec = importlib.util.spec_from_file_location("xagent_context_manager", _SRC)
if _spec is None or _spec.loader is None:
    raise ImportError(f"无法加载上下文压缩模块：{_SRC}")

_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# ---- 对外导出 ----
ContextManager = _mod.ContextManager
CompactError = _mod.CompactError
WARN_RATIO = _mod.WARN_RATIO
COMPACT_PROMPT = _mod.COMPACT_PROMPT
estimate_text_tokens = _mod.estimate_text_tokens
estimate_messages_tokens = _mod.estimate_messages_tokens
format_k = _mod.format_k
ratio_color = _mod.ratio_color
resolve_window = _mod.resolve_window

__all__ = [
    "ContextManager", "CompactError", "WARN_RATIO", "COMPACT_PROMPT",
    "estimate_text_tokens", "estimate_messages_tokens", "format_k",
    "ratio_color", "resolve_window",
]
