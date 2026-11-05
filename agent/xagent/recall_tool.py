# -*- coding: utf-8 -*-
"""recallContext 工具：在压缩归档里做本地全文关键词检索（不依赖向量库）。

归档文件是 ``.agents/context/<编号>.jsonl``，每行一条消息，由
``context_manager.ContextManager.save_archive`` 写出。

检索规则（刻意做得很朴素，方便同学读懂和改）：
    1. 把 text 按空白切成若干关键词，全部转小写；
    2. 一条消息里命中越多关键词，得分越高（命中的词数优先，其次是出现次数）；
    3. 按得分排序，返回片段、归档编号、行号、角色，并限制总长度，
       避免检索结果再次把上下文塞满。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from context_manager import list_archives, read_archive

# 返回结果的硬限制：片段数、单个片段长度、所有片段总字符数
MAX_HITS = 10
DEFAULT_HITS = 6
SNIPPET_HEAD = 120        # 命中点之前保留的字符
SNIPPET_TAIL = 240        # 命中点之后保留的字符
TOTAL_CHARS = 3_000       # 全部结果的总字符上限

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "recallContext",
        "description": (
            "检索此前被 /compact 压缩归档的原始对话记录。"
            "当上下文摘要里缺少某个细节（例如之前的文件路径、报错信息、工具返回结果、"
            "用户的原话或已确定的方案）时，调用本工具按关键词找回原文。"
            "不传 id 就在全部归档里检索；传 id 只查指定的那一份。"
            "使用本地全文关键词匹配，需自行挑选合适的关键词（人/物/路径/报错片段）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要查找的关键词或文本内容；多个关键词用空格分隔（同时出现的内容排更前）",
                },
                "id": {
                    "type": "string",
                    "description": "可选，指定归档编号（形如 20261022-153000）。不填则检索 .agents/context 下所有归档",
                },
                "limit": {
                    "type": "integer",
                    "description": f"可选，最多返回几条片段，默认 {DEFAULT_HITS}，上限 {MAX_HITS}",
                },
            },
            "required": ["text"],
        },
    },
}


def _haystack(msg: dict) -> str:
    """把一条消息压成可检索的字符串（正文 + 工具调用名与参数 + 工具调用 id）。"""
    parts = [str(msg.get("content") or "")]
    for tc in msg.get("tool_calls") or []:
        fn = (tc or {}).get("function") or {}
        parts.append(str(fn.get("name") or ""))
        parts.append(str(fn.get("arguments") or ""))
    if msg.get("tool_call_id"):
        parts.append(str(msg["tool_call_id"]))
    if msg.get("name"):
        parts.append(str(msg["name"]))
    return "\n".join(parts)


def _snippet(hay: str, terms: list[str]) -> tuple[str, int]:
    """截取命中点附近的一段文本，返回 (片段, 首个命中位置)。"""
    low = hay.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=-1)
    if pos < 0:
        pos = 0
    start = max(0, pos - SNIPPET_HEAD)
    end = min(len(hay), pos + SNIPPET_TAIL)
    text = hay[start:end]
    if start > 0:
        text = "…" + text
    if end < len(hay):
        text = text + "…"
    return text, pos


def _pick_archives(archive_dir: Path, archive_id: str | None) -> list[Path]:
    files = list_archives(archive_dir)
    if not archive_id:
        return files
    want = archive_id.strip()
    if want.endswith(".jsonl"):
        want = want[:-6]
    return [p for p in files if p.stem == want]


def search(archive_dir: Path, text: str, archive_id: str | None = None,
           limit: int | None = None) -> dict:
    """执行检索，返回可直接 json.dumps 的结构。"""
    terms = [t for t in re.split(r"\s+", (text or "").strip().lower()) if t]
    if not terms:
        return {"error": "text 不能为空，请给出要查找的关键词"}

    try:
        limit = int(limit) if limit else DEFAULT_HITS
    except (TypeError, ValueError):
        limit = DEFAULT_HITS
    limit = max(1, min(limit, MAX_HITS))

    files = _pick_archives(Path(archive_dir), archive_id)
    if not files:
        msg = (f"没有找到编号为 {archive_id} 的归档" if archive_id
               else "还没有任何上下文归档（执行 /compact 压缩后才会生成）")
        return {"archive_dir": str(archive_dir), "text": text, "hits": [],
                "message": msg}

    hits: list[dict] = []
    for path in files:
        for line_no, msg in enumerate(read_archive(path), start=1):
            hay = _haystack(msg)
            if not hay.strip():
                continue
            low = hay.lower()
            matched = [t for t in terms if t in low]
            if not matched:
                continue
            score = len(matched) * 10 + sum(low.count(t) for t in matched)
            snip, _ = _snippet(hay, matched)
            hits.append({
                "id": path.stem,
                "line": line_no,
                "role": msg.get("role", "unknown"),
                "score": score,
                "matched": matched,
                "snippet": snip,
            })

    hits.sort(key=lambda h: (-h["score"], h["id"], h["line"]))
    total = 0
    kept: list[dict] = []
    for h in hits[:limit]:
        total += len(h["snippet"])
        if kept and total > TOTAL_CHARS:
            break
        kept.append(h)

    result = {
        "archive_dir": str(archive_dir),
        "text": text,
        "archives_scanned": len(files),
        "matched": len(hits),
        "returned": len(kept),
        "hits": kept,
    }
    if not kept:
        result["message"] = "没有匹配内容。可以换更短、更具体的关键词（文件名、报错片段、函数名）。"
    elif len(hits) > len(kept):
        result["notice"] = f"共 {len(hits)} 条匹配，只返回得分最高的 {len(kept)} 条；可换更精确的关键词缩小范围。"
    return result


def execute_tool(arguments: dict, archive_dir) -> str:
    """工具入口：供 xagent.dispatch_tool 调用。"""
    args = arguments or {}
    text = (args.get("text") or "").strip()
    if not text:
        return json.dumps({"error": "缺少必需参数 text"}, ensure_ascii=False)
    try:
        payload = search(Path(archive_dir), text, args.get("id"), args.get("limit"))
    except Exception as e:                    # 检索失败不能把整轮对话拖崩
        return json.dumps({"error": f"检索归档失败：{e}"}, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)
