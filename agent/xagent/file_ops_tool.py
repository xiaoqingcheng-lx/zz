# -*- coding: utf-8 -*-
"""fileOps —— 技能目录内的文件操作工具（createSkill 的配套工具）。

实验要求（第 139 行）：创建 Skill 时若还需要 references/、scripts/ 等目录或其他辅助文件，
LLM 应继续调用 fileOps 完成。

设计要点：
1. 三个动作：``make_dir`` / ``write_file`` / ``list_files``；
2. 所有路径都被限制在**技能根目录**（``.agents/skills``）内，越界直接拒绝；
3. 写操作自动补建父目录，内容统一 UTF-8；
4. 返回 JSON（含真实路径与字节数），方便 LLM 判断下一步。
"""
from __future__ import annotations

import json
from pathlib import Path

MAX_WRITE_CHARS = 200_000
MAX_LIST_ENTRIES = 200

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fileOps",
        "description": (
            "在技能目录（.agents/skills）内创建目录或写文件，"
            "用于给新建的 Skill 补充 references/、scripts/ 等辅助内容。"
            "路径可以写相对技能根目录的路径（如 my-skill/references/guide.md）"
            "或绝对路径，但必须位于技能根目录内。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["make_dir", "write_file", "list_files"],
                    "description": "要执行的操作",
                },
                "path": {
                    "type": "string",
                    "description": "目标路径（相对技能根目录或绝对路径），list_files 用目录路径",
                },
                "content": {
                    "type": "string",
                    "description": "write_file 时要写入的完整文本内容（UTF-8）",
                },
            },
            "required": ["action", "path"],
        },
    },
}


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _resolve(root: Path, raw: str) -> tuple[Path | None, str | None]:
    """把用户给的路径解析到 root 内；越界返回错误。"""
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        return None, "path 不能为空"
    candidate = Path(raw)
    target = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved = target.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)          # 越界会抛 ValueError
    except ValueError:
        return None, f"拒绝操作：{raw} 解析到技能根目录之外（{root}）"
    except OSError as e:
        return None, f"路径解析失败：{e}"
    return resolved, None


def execute_tool(root: Path, arguments: dict) -> str:
    """执行 fileOps，返回 JSON 字符串作为 role=tool 消息。"""
    action = str(arguments.get("action", "") or "").strip()
    raw_path = str(arguments.get("path", "") or "")
    content = arguments.get("content", "")

    if action not in ("make_dir", "write_file", "list_files"):
        return _dump({
            "error": f"未知 action：{action or '(空)'}",
            "allowed": ["make_dir", "write_file", "list_files"],
        })

    target, error = _resolve(Path(root), raw_path)
    if error:
        return _dump({"error": error, "action": action})

    # ---------------- 建目录 ----------------
    if action == "make_dir":
        if target.exists() and not target.is_dir():
            return _dump({"error": f"{target} 已存在且不是目录"})
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return _dump({"error": f"创建目录失败：{e}"})
        return _dump({"ok": True, "action": action, "path": str(target)})

    # ---------------- 写文件 ----------------
    if action == "write_file":
        text = "" if content is None else str(content)
        if len(text) > MAX_WRITE_CHARS:
            return _dump({"error": f"内容过长（{len(text)} 字符，上限 {MAX_WRITE_CHARS}）"})
        if target.exists() and target.is_dir():
            return _dump({"error": f"{target} 是目录，不能写入文件"})
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        except OSError as e:
            return _dump({"error": f"写入失败：{e}"})
        return _dump({
            "ok": True,
            "action": action,
            "path": str(target),
            "bytes": len(text.encode("utf-8")),
        })

    # ---------------- 列目录 ----------------
    if not target.exists():
        return _dump({"error": f"目录不存在：{target}"})
    if not target.is_dir():
        return _dump({"error": f"{target} 不是目录"})
    try:
        entries = []
        for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            item = {"name": p.name, "type": "dir" if p.is_dir() else "file"}
            if p.is_file():
                item["bytes"] = p.stat().st_size
            entries.append(item)
    except OSError as e:
        return _dump({"error": f"读取目录失败：{e}"})
    return _dump({
        "ok": True,
        "action": action,
        "path": str(target),
        "count": len(entries),
        "entries": entries[:MAX_LIST_ENTRIES],
        "truncated": len(entries) > MAX_LIST_ENTRIES,
    })
