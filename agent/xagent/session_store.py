# -*- coding: utf-8 -*-
"""session_store —— 会话持久化：/save /new /resume 的底层实现。

设计：
    · 会话存成 JSON：<项目根>/<sessions.dir>/<会话ID>.json（默认 .agents/sessions/）；
    · 会话 ID 用时间戳（YYYYMMDD-HHMMSS），文件名即 ID，天然按时间排序；
    · history 原样保存（含 tool_calls 与 role=tool 的完整轨迹），
      恢复后 /compact 照样能归档压缩；
    · AGENTS.md 注入记录写进 events 数组（「持久化到会话事件日志」），
      注入的那条消息本身也在 history 里，一次注入全程复用。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

# 会话里两类特殊消息的标记（不计入轮数统计）
AGENTS_MD_HEADER = "【AGENTS.md 项目说明】"
SUMMARY_HEADER_MARK = "【上下文压缩摘要】"

MAX_TITLE = 40          # 会话标题最大字符数
MAX_SESSIONS = 200      # 列表最多返回条数


# --------------------------------------------------------------------------- #
# 目录与文件
# --------------------------------------------------------------------------- #
def sessions_dir(project_root: Path, sub: str = ".agents/sessions") -> Path:
    return (Path(project_root) / sub).resolve()


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def session_path(project_root: Path, session_id: str,
                 sub: str = ".agents/sessions") -> Path:
    return sessions_dir(project_root, sub) / f"{session_id}.json"


# --------------------------------------------------------------------------- #
# 标题与轮数
# --------------------------------------------------------------------------- #
def _is_special(msg: dict) -> bool:
    """注入的 AGENTS.md / 压缩摘要这类特殊消息不算「用户提问」。"""
    if msg.get("role") != "user":
        return False
    text = str(msg.get("content") or "")
    return text.startswith(AGENTS_MD_HEADER) or text.startswith(SUMMARY_HEADER_MARK)


def session_title(history: list) -> str:
    """取第一条真实用户消息做标题，截断到 MAX_TITLE。"""
    for m in history:
        if m.get("role") == "user" and not _is_special(m):
            text = " ".join(str(m.get("content") or "").split())
            if text:
                return text[:MAX_TITLE] + ("…" if len(text) > MAX_TITLE else "")
    return "（空会话）"


def count_turns(history: list) -> int:
    return sum(1 for m in history if not _is_special(m) and m.get("role") == "user")


# --------------------------------------------------------------------------- #
# 保存 / 列表 / 读取
# --------------------------------------------------------------------------- #
def save_session(project_root: Path, history: list,
                 session_id: str | None = None, sub: str = ".agents/sessions",
                 model: str = "", events: list | None = None,
                 title: str | None = None) -> dict:
    """保存（或覆盖更新）一个会话，返回会话元信息。

    已有会话再次保存时保留 created_at，只更新 updated_at —— /new 的
    自动保存和每轮结束的自动保存都走这里。
    """
    sid = session_id or new_session_id()
    path = session_path(project_root, sid, sub)
    path.parent.mkdir(parents=True, exist_ok=True)

    meta: dict = {}
    if path.is_file():                       # 更新已有会话：保留旧元信息
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}

    now = datetime.now().isoformat(timespec="seconds")
    meta.update({
        "id": sid,
        "title": title or session_title(history),
        "turns": count_turns(history),
        "messages": len(history),
        "model": model,
        "updated_at": now,
    })
    meta.setdefault("created_at", now)
    if events:
        merged = meta.setdefault("events", [])
        merged.extend(events)
    meta["history"] = list(history)

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)                        # 原子替换，写一半不会被读到
    return meta


def list_sessions(project_root: Path, sub: str = ".agents/sessions",
                  limit: int = MAX_SESSIONS) -> list[dict]:
    """按更新时间倒序列出会话（不含 history 本身）。"""
    out: list[dict] = []
    root = sessions_dir(project_root, sub)
    if not root.is_dir():
        return out
    for p in root.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "id": data.get("id") or p.stem,
            "title": data.get("title") or "（未命名）",
            "turns": data.get("turns", 0),
            "messages": data.get("messages", 0),
            "updated_at": data.get("updated_at", ""),
            "created_at": data.get("created_at", ""),
            "model": data.get("model", ""),
            "path": p,
        })
    out.sort(key=lambda d: (d["updated_at"], d["id"]), reverse=True)
    return out[:limit]


def load_session(project_root: Path, session_id: str,
                 sub: str = ".agents/sessions") -> tuple[list, dict]:
    """读取一个会话，返回 (history, meta)；找不到抛 FileNotFoundError。"""
    p = session_path(project_root, session_id, sub)
    if not p.is_file():
        raise FileNotFoundError(f"会话不存在：{p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return list(data.get("history") or []), data


def delete_session(project_root: Path, session_id: str,
                   sub: str = ".agents/sessions") -> bool:
    p = session_path(project_root, session_id, sub)
    if p.is_file():
        p.unlink()
        return True
    return False


# --------------------------------------------------------------------------- #
# AGENTS.md：一次注入，全程复用
# --------------------------------------------------------------------------- #
def agents_md_path(project_root: Path) -> Path:
    return Path(project_root) / "AGENTS.md"


def agents_md_message(project_root: Path) -> dict | None:
    """项目根有 AGENTS.md 就返回要注入的那条 user 消息，否则 None。

    只在「新建会话」时调用一次；消息随 history 持久化，
    之后每一轮直接复用历史里的这一条，不再重复注入——
    每轮请求里它内容完全一致，前缀稳定，利于服务端 KV 缓存命中。
    """
    p = agents_md_path(project_root)
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    return {
        "role": "user",
        "content": f"{AGENTS_MD_HEADER}\n以下是本项目根目录 AGENTS.md 的内容，"
                   f"请在本次会话全程遵守其中的约定：\n\n{text}",
    }


def inject_agents_md(history: list, project_root: Path) -> tuple[list, dict | None]:
    """给空会话补上 AGENTS.md 注入消息，返回 (新历史, 注入事件或 None)。"""
    if history:                              # 只对空会话注入，避免重复
        return list(history), None
    msg = agents_md_message(project_root)
    if msg is None:
        return list(history), None
    event = {
        "type": "agents_md_injected",
        "at": datetime.now().isoformat(timespec="seconds"),
        "path": str(agents_md_path(project_root)),
        "chars": len(msg["content"]),
    }
    return [msg], event
