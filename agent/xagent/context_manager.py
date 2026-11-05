# -*- coding: utf-8 -*-
"""上下文管理：Token 计量、阈值告警、原始归档、LLM 压缩、状态栏渲染。

课程要求「简单可理解」，所以这里只做四件事，不引入向量库 / Embedding：

    1. 计量：优先用 API 返回的 usage.prompt_tokens，拿不到就按字符估算
       （中文 1 字≈1 token，英文约 3.5 字符≈1 token，另加每条消息的固定开销）；
    2. 归档：压缩前把原始消息逐条写进 ``.agents/context/<编号>.jsonl``，
       写完 fsync + 原子改名，确认落盘成功才允许继续压缩；
    3. 压缩：把历史渲染成可读文本 → 调一次（或分片多次）纯文本 LLM 生成摘要 →
       用「摘要 + 归档说明」一条消息替换原有历史，System Prompt 与工具定义保持不动；
    4. 状态：算出「已用 / 窗口 / 百分比」，供 TUI 状态栏显示。

失败原则：任何一步出错都保留原有上下文，只向上报告错误，让用户重新执行 /compact。
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
WARN_RATIO = 0.70          # 达到窗口 70% 就告警并暂停普通输入
DEFAULT_WINDOW = 128_000   # 查不到模型窗口时的兜底值（界面上标注「默认」）
SUMMARY_TARGET = 5_000     # 摘要目标长度（Tokens）

# 常见模型的上下文窗口（Tokens）。查不到就走 DEFAULT_WINDOW 并标「默认」
MODEL_WINDOWS = {
    "qwen-plus": 131_072,
    "qwen-plus-latest": 131_072,
    "qwen-turbo": 131_072,
    "qwen-turbo-latest": 131_072,
    "qwen-max": 32_768,
    "qwen-max-latest": 32_768,
    "qwen-long": 1_000_000,
    "qwen3-max": 131_072,
    "qwen-vl-max": 131_072,
    "qwen2.5-72b-instruct": 131_072,
    "qwen2.5-32b-instruct": 131_072,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-3.5-turbo": 16_385,
    "deepseek-chat": 65_536,
    "deepseek-reasoner": 65_536,
}

# 压缩专用 Prompt（课程给定的原版，逐字使用）
COMPACT_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""

# 分片压缩时每一片用的提示词（历史太长、一次塞不进窗口时才会用到）
CHUNK_PROMPT = """你是一名 AI Agent 的上下文管理助手。下面是一段历史对话中的**一部分**（不是全部）。
请把它压缩成约 800 Tokens 的要点清单，供后续汇总使用。

保留：用户的要求与约束、已完成的工作与验证结果、当前状态、关键技术信息（路径 / 函数 / 命令 / 报错）、
已确定的技术方案与原因、下一步待办。删除寒暄与重复讨论。用 Markdown 无序列表输出，不要附加解释。"""

SUMMARY_HEADER = (
    "【上下文压缩摘要】以下是此前会话的摘要（原始对话已归档，可用 recallContext 工具检索）。"
    "请在此基础上继续完成用户的任务。\n\n"
)

ARCHIVE_NOTE = (
    "此前上下文已于 {when} 完成压缩，原始上下文保存在编号为 {archive_id} 的归档文件中。"
    "如需查找历史信息，请使用 recallContext 工具。"
)

# 单条工具返回在「交给摘要模型」时的截断长度（完整内容仍在归档里）
TRANSCRIPT_ITEM_LIMIT = 2_000


class CompactError(RuntimeError):
    """压缩流程失败：调用方应保留原上下文并提示用户重试。"""


# --------------------------------------------------------------------------- #
# Token 估算
# --------------------------------------------------------------------------- #
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def estimate_text_tokens(text) -> int:
    """粗略估算文本 Token 数：中文按字，英文按 3.5 字符。"""
    if text is None:
        return 0
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return int(cjk + (len(text) - cjk) / 3.5) + 1


def estimate_message_tokens(msg: dict) -> int:
    """单条消息的 Token 估算：正文 + 工具调用参数 + 固定开销。"""
    total = 4                                     # role / 分隔符等固定开销
    total += estimate_text_tokens(msg.get("content") or "")
    calls = msg.get("tool_calls") or []
    for tc in calls:
        fn = (tc or {}).get("function") or {}
        total += 4 + estimate_text_tokens(fn.get("name") or "")
        total += estimate_text_tokens(fn.get("arguments") or "")
    if msg.get("tool_call_id"):
        total += 4
    return total


def estimate_messages_tokens(messages) -> int:
    """整段上下文的 Token 估算（System Prompt、用户输入、历史、工具消息都算）。"""
    return sum(estimate_message_tokens(m) for m in messages or []) + 3


# --------------------------------------------------------------------------- #
# 窗口大小 / 数字格式化
# --------------------------------------------------------------------------- #
def resolve_window(model: str, explicit: int | None = None) -> tuple[int, bool]:
    """返回 (上下文窗口, 是否使用默认值)。

    优先级：显式参数 → 环境变量 XAGENT_CONTEXT_WINDOW → 内置模型表 → 默认 128k。
    """
    if explicit and explicit > 0:
        return int(explicit), False
    env = os.environ.get("XAGENT_CONTEXT_WINDOW", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env), False
    name = (model or "").strip().lower()
    if name in MODEL_WINDOWS:
        return MODEL_WINDOWS[name], False
    for key, size in MODEL_WINDOWS.items():       # 形如 qwen-plus-2025-xx 的版本后缀
        if name.startswith(key):
            return size, False
    return DEFAULT_WINDOW, True


def format_k(tokens: int) -> str:
    """按 1024 进位显示成 k：131072 → 128k，12288 → 12k，999 → 999。

    用 1024 是为了让窗口显示成大家熟悉的 128k / 32k，而不是 131.1k。
    """
    tokens = int(tokens)
    if tokens < 1_000:
        return str(tokens)
    value = tokens / 1024
    if abs(value - round(value)) < 0.05:
        return f"{int(round(value))}k"
    return f"{value:.1f}k"


# --------------------------------------------------------------------------- #
# 终端颜色（Windows 需要显式打开 VT 处理，否则转义序列会当成乱码打印）
# --------------------------------------------------------------------------- #
_COLOR = {"reset": "\033[0m", "dim": "\033[2m", "green": "\033[32m",
          "yellow": "\033[33m", "red": "\033[31m", "cyan": "\033[36m"}


def enable_ansi() -> bool:
    """在当前控制台打开 ANSI 支持；不支持的终端返回 False。"""
    if os.environ.get("NO_COLOR"):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-11)             # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(k32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def colorize(text: str, color: str, use_color: bool = True) -> str:
    if not use_color or color not in _COLOR:
        return text
    return _COLOR[color] + text + _COLOR["reset"]


def ratio_color(ratio: float) -> str:
    if ratio >= WARN_RATIO:
        return "red"
    if ratio >= 0.5:
        return "yellow"
    return "green"


def render_status_bar(used: int, window: int, is_default: bool,
                      ratio: float | None = None, use_color: bool = True,
                      width: int = 10) -> str:
    """生成一行状态栏：``上下文 12.3k / 128k（默认） · 9.6% · █░░░░░░░░░``。"""
    ratio = ratio if ratio is not None else (used / window if window else 0.0)
    ratio = max(0.0, min(ratio, 1.0))
    filled = max(0, min(width, int(round(ratio * width))))
    bar = "█" * filled + "░" * (width - filled)
    tail = "（默认）" if is_default else ""
    body = (f"上下文 {format_k(used)} / {format_k(window)}{tail} · "
            f"{ratio * 100:.1f}% · {bar}")
    return colorize(body, ratio_color(ratio), use_color)


# --------------------------------------------------------------------------- #
# 把消息渲染成「给摘要模型看的纯文本」
# --------------------------------------------------------------------------- #
def _one_line(text: str, limit: int) -> str:
    text = (text or "").replace("\r\n", "\n")
    if len(text) > limit:
        text = text[:limit] + f"\n…（此处已截断，原文共 {len(text)} 字符，完整内容见归档）"
    return text


def render_transcript(messages, archive_id: str = "", header: str = "") -> str:
    """把消息列表渲染成带角色的 Markdown 文本，供压缩 Prompt 使用。

    System Prompt 不参与压缩（它每轮实时重建），这里显式标注跳过。
    """
    lines: list[str] = []
    if header:
        lines.append(header)
    lines.append(f"> 共 {len(messages)} 条消息，原始记录归档编号：{archive_id or '未归档'}\n")
    for idx, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        if role == "system":
            lines.append(f"### [{idx}] system（System Prompt 每轮重建，此处略）\n")
            continue
        head = f"### [{idx}] {role}"
        if msg.get("tool_call_id"):
            head += f" · tool_call_id={msg['tool_call_id']}"
        lines.append(head)
        content = msg.get("content")
        if content:
            lines.append(_one_line(str(content), TRANSCRIPT_ITEM_LIMIT))
        for tc in msg.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            lines.append(f"- 调用工具 `{fn.get('name')}`，参数：`{_one_line(fn.get('arguments') or '', 800)}`")
        lines.append("")
    return "\n".join(lines)


def _slice_long_block(text: str, budget: int) -> list[str]:
    """把单段超长文本（比如一大坨工具输出）按字符数硬切成若干片。"""
    step = max(200, int(budget * 1.2))     # 中文约 1 字 1 token，留点余量
    return [text[i:i + step] for i in range(0, len(text), step)] or [""]


def split_by_tokens(text: str, budget: int) -> list[str]:
    """按 Token 预算把长文本切成若干片（先按段落切，单段太长再按字符切）。"""
    budget = max(1_000, int(budget))
    if estimate_text_tokens(text) <= budget:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        pieces = _slice_long_block(para, budget) if estimate_text_tokens(para) > budget else [para]
        for piece in pieces:
            cost = estimate_text_tokens(piece) + 2
            if size + cost > budget and buf:
                chunks.append("\n\n".join(buf))
                buf, size = [], 0
            buf.append(piece)
            size += cost
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


# --------------------------------------------------------------------------- #
# 归档读写（recall_tool 也复用这里的路径规则）
# --------------------------------------------------------------------------- #
ARCHIVE_SUFFIX = ".jsonl"


def default_archive_dir(project_root: Path) -> Path:
    """项目本地归档目录：``<项目根>/.agents/context``，可用环境变量覆盖。"""
    env = os.environ.get("XAGENT_CONTEXT_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path(project_root) / ".agents" / "context").resolve()


def list_archives(archive_dir: Path) -> list[Path]:
    """列出所有归档文件，新的在前。"""
    d = Path(archive_dir)
    if not d.is_dir():
        return []
    files = [p for p in d.iterdir() if p.is_file() and p.suffix == ARCHIVE_SUFFIX]
    return sorted(files, key=lambda p: (p.stem, p.stat().st_mtime), reverse=True)


def read_archive(path: Path) -> list[dict]:
    """读一个归档文件，返回消息字典列表（跳过 _meta 行）。"""
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if "_meta" in obj:
                    continue
                out.append(obj)
    except OSError:
        return []
    return out


# --------------------------------------------------------------------------- #
# 压缩日志：记录「这一次到底压掉了哪些内容」
# --------------------------------------------------------------------------- #
COMPACT_LOG_NAME = "compact.log"


def _short(text, limit: int = 70) -> str:
    """压成一行并截断（用于日志里的诉求/标题，不带长提示语）。"""
    s = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    return s if len(s) <= limit else s[:limit] + "…"


def describe_history(messages) -> dict:
    """统计一批历史消息，回答「压了什么」：条数、角色分布、Token、用户诉求、涉及工具。"""
    msgs = list(messages or [])
    roles = {"system": 0, "user": 0, "assistant": 0, "tool": 0, "other": 0}
    topics: list[str] = []
    tools: list[str] = []
    for msg in msgs:
        role = str(msg.get("role") or "other").lower()
        roles[role if role in roles else "other"] += 1
        content = str(msg.get("content") or "")
        # 压缩摘要本身不算「用户诉求」，否则会把上一次的摘要当成本轮话题
        if role == "user" and content and not content.startswith(SUMMARY_HEADER[:8]):
            one = _short(content)
            if one:
                topics.append(one)
        for tc in (msg.get("tool_calls") or []):
            fn = (tc or {}).get("function") or {}
            name = str(fn.get("name") or "").strip()
            if name and name not in tools:
                tools.append(name)
    return {
        "total": len(msgs),
        "roles": roles,
        "tokens": estimate_messages_tokens(msgs),
        "topics": topics,
        "tools": tools,
    }


def summary_outline(summary: str, limit: int = 12) -> list[str]:
    """从摘要里抽出 Markdown 标题，作为「摘要保留了哪些块」的目录。"""
    out: list[str] = []
    for line in (summary or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            title = s.lstrip("#").strip()
            if title:
                out.append(_short(title, 60))
        if len(out) >= limit:
            break
    return out


def describe_block(info: dict, topic_limit: int = 5) -> list[str]:
    """把压缩信息渲染成「本次压缩了什么」的纯文本清单（命令行与 TUI 共用）。"""
    before = info.get("before") or {}
    roles = before.get("roles") or {}
    lines = ["📦 本次压缩了什么"]
    lines.append(
        f"  原始消息  {before.get('total', info.get('replaced', 0))} 条"
        f"（user {roles.get('user', 0)} / assistant {roles.get('assistant', 0)}"
        f" / tool {roles.get('tool', 0)}）｜ 约 {format_k(before.get('tokens', 0))} Tokens"
    )
    tools = before.get("tools") or []
    if tools:
        more = f" 等 {len(tools)} 个" if len(tools) > 6 else ""
        lines.append(f"  涉及工具  {'、'.join(tools[:6])}{more}")

    topics = before.get("topics") or []
    if topics:
        lines.append(f"  用户诉求  （共 {len(topics)} 条，列出前 {min(topic_limit, len(topics))} 条）")
        for i, t in enumerate(topics[:topic_limit], 1):
            lines.append(f"            {i}. {t}")
        if len(topics) > topic_limit:
            lines.append(f"            … 另有 {len(topics) - topic_limit} 条，见归档原文")

    outline = info.get("outline") or []
    if outline:
        lines.append("  摘要结构  " + " ／ ".join(outline[:6])
                     + (f" 等 {len(outline)} 节" if len(outline) > 6 else ""))
    elif info.get("summary"):
        lines.append("  摘要开头  " + _short(info["summary"], 60))

    if info.get("source_chars"):
        lines.append(
            f"  原文体积  {info['source_chars']:,} 字符 ≈ "
            f"{format_k(info.get('source_tokens', 0))} Tokens（送入摘要模型的完整记录）"
        )

    lines.append(
        f"  摘要体积  {info.get('chars', 0):,} 字符 ≈ {format_k(info.get('tokens_estimate', 0))} Tokens"
        f"（{format_k(before.get('tokens', 0))} → {format_k(info.get('tokens_estimate', 0))}）"
    )
    lines.append(f"  归档文件  {info.get('path', '')}")
    if info.get("id"):
        lines.append(f"  检索方式  recallContext(id=\"{info['id']}\", text=\"关键词\")")
    if info.get("log_path"):
        lines.append(f"  压缩日志  {info['log_path']}")
    if info.get("log_error"):
        lines.append(f"  ⚠️ 日志写入失败：{info['log_error']}")
    return lines


def append_compact_log(log_path: Path, info: dict) -> Path:
    """把本次压缩追加写进 compact.log（人可读，一行一条关键信息）。"""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    before = info.get("before") or {}
    roles = before.get("roles") or {}
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = ["=" * 62]
    lines.append(f"[{stamp}] 压缩完成 · 编号 {info.get('id', '')} · 会话模型 {info.get('model', '') or '未知'}")
    lines.append(
        f"  原始消息：{before.get('total', 0)} 条"
        f"（user {roles.get('user', 0)} / assistant {roles.get('assistant', 0)}"
        f" / tool {roles.get('tool', 0)}），约 {format_k(before.get('tokens', 0))} Tokens"
    )
    if before.get("tools"):
        lines.append(f"  涉及工具：{'、'.join(before['tools'])}")
    for i, t in enumerate((before.get("topics") or [])[:8], 1):
        lines.append(f"  诉求 {i}：{t}")
    if info.get("outline"):
        lines.append(f"  摘要结构：{' ／ '.join(info['outline'])}")
    elif info.get("summary"):
        lines.append(f"  摘要开头：{_short(info['summary'], 60)}")
    if info.get("source_chars"):
        lines.append(
            f"  原文体积：{info['source_chars']:,} 字符 ≈ {format_k(info.get('source_tokens', 0))} Tokens"
        )
    lines.append(
        f"  摘要体积：{info.get('chars', 0):,} 字符 ≈ {format_k(info.get('tokens_estimate', 0))} Tokens"
        f"（压缩 {format_k(before.get('tokens', 0))} → {format_k(info.get('tokens_estimate', 0))}）"
    )
    lines.append(f"  归档文件：{info.get('path', '')}")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def read_compact_log(log_path: Path, blocks: int = 3) -> str:
    """读最近 N 次压缩日志（用于 /logs 查看）。"""
    path = Path(log_path)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    parts = [b for b in text.split("=" * 62) if b.strip()]
    return ("=" * 62).join([""] + parts[-blocks:]).strip() if parts else ""


# --------------------------------------------------------------------------- #
# 上下文管理器
# --------------------------------------------------------------------------- #
class ContextManager:
    """单个会话的上下文状态：用量、告警、归档、压缩。"""

    def __init__(self, project_root: Path, model: str,
                 window: int | None = None, archive_dir: Path | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.model = model or ""
        self.window, self.window_is_default = resolve_window(model, window)
        self.archive_dir = Path(archive_dir).resolve() if archive_dir else default_archive_dir(self.project_root)
        self.api_tokens = 0                    # 最近一次 API 返回的真实 prompt_tokens
        self.api_source = ""                   # "api" / "estimate"
        self.blocked = False                   # 达阈值后暂停普通输入
        self.last_compact: dict | None = None  # 最近一次压缩的元信息

    # ---------------- 计量 ----------------
    def note_usage(self, usage: dict | None) -> None:
        """记录 API 返回的 usage（有就用真值，没有就维持估算）。"""
        if not isinstance(usage, dict):
            return
        tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("total_tokens")
        if isinstance(tokens, int) and tokens > 0:
            self.api_tokens = tokens
            self.api_source = "api"

    def reset_usage(self) -> None:
        """上下文被替换后，旧的真实读数失效。"""
        self.api_tokens = 0
        self.api_source = "estimate"
        self.blocked = False

    def used_tokens(self, messages) -> int:
        """当前上下文占用：有 API 真值就优先用，估算只做兜底与下限修正。

        取 max 的原因：API 的 prompt_tokens 是上一次请求的读数，之后追加的消息
        （助手回复、工具结果）还没算进去，估算值通常更大，取大更安全。
        上下文被替换（压缩）后调用 reset_usage() 清掉旧读数，不会残留虚高值。
        """
        est = estimate_messages_tokens(messages)
        if self.api_tokens > 0:
            return max(est, self.api_tokens)
        return est

    def ratio(self, used: int) -> float:
        return used / self.window if self.window else 0.0

    def update_blocked(self, used: int) -> bool:
        """达到 70% 就挂起输入闸门，返回是否已阻断。"""
        self.blocked = self.ratio(used) >= WARN_RATIO
        return self.blocked

    # ---------------- 状态栏 ----------------
    def status_bar(self, messages, use_color: bool = True) -> str:
        used = self.used_tokens(messages)
        return render_status_bar(used, self.window, self.window_is_default,
                                 self.ratio(used), use_color)

    def warning_line(self, messages, use_color: bool = True) -> str:
        """超过阈值时的一行醒目提示（未超阈值返回空串）。"""
        used = self.used_tokens(messages)
        ratio = self.ratio(used)
        if ratio < WARN_RATIO:
            return ""
        text = (f"⚠️ 上下文已占用 {ratio * 100:.1f}%（阈值 {WARN_RATIO * 100:.0f}%），"
                f"请执行 /compact 压缩后再继续。")
        return colorize(text, "red", use_color)

    def summary_line(self, messages) -> str:
        """纯文本状态（写日志 / 打印用，不含 ANSI）。"""
        used = self.used_tokens(messages)
        tail = "（默认）" if self.window_is_default else ""
        return (f"上下文 {format_k(used)} / {format_k(self.window)}{tail} · "
                f"{self.ratio(used) * 100:.1f}% · 来源 {self.api_source or 'estimate'}")

    # ---------------- 归档 ----------------
    def new_archive_id(self) -> str:
        """生成归档编号：YYYYMMDD-HHMMSS；同一秒内撞名就等到下一秒再用。"""
        while True:
            aid = datetime.now().strftime("%Y%m%d-%H%M%S")
            if not (self.archive_dir / f"{aid}{ARCHIVE_SUFFIX}").exists():
                return aid
            time.sleep(0.2)

    def save_archive(self, messages, archive_id: str) -> Path:
        """把原始消息逐条写入 jsonl；必须真正落盘成功，否则抛 CompactError。"""
        path = self.archive_dir / f"{archive_id}{ARCHIVE_SUFFIX}"
        tmp = path.with_suffix(path.suffix + ".tmp")
        meta = {
            "_meta": {
                "id": archive_id,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "model": self.model,
                "messages": len(messages),
                "tokens_estimate": estimate_messages_tokens(messages),
                "note": "压缩前的原始上下文，按角色与顺序逐条保存，供 recallContext 检索",
            }
        }
        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)   # 建目录失败也算归档失败
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
                for idx, msg in enumerate(messages):
                    record = {"index": idx}
                    for key in ("role", "content", "name", "tool_call_id", "tool_calls"):
                        if key in msg and msg[key] is not None:
                            record[key] = msg[key]
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())          # 真正刷到磁盘，而不是停在缓冲区
            os.replace(tmp, path)             # 原子落位，不会留下半截文件
        except OSError as e:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise CompactError(f"原始上下文归档失败：{e}") from e
        return path

    # ---------------- 压缩 ----------------
    def compact(self, history, chat_fn, verbose: bool = False,
                printer=print) -> tuple[list, dict]:
        """执行完整压缩流程，返回 (新历史, 信息字典)。

        chat_fn(system_prompt, user_content) -> str，必须是不带工具的纯文本调用，
        这样压缩期间不可能再触发 Function Calling。
        """
        history = list(history or [])
        if not history:
            raise CompactError("当前会话还没有可压缩的历史消息。")

        archive_id = self.new_archive_id()
        path = self.save_archive(history, archive_id)          # ① 先归档，失败就中止
        if verbose:
            printer(f"  💾 原始上下文已归档：{path}")

        transcript = render_transcript(
            history, archive_id,
            header=f"会话模型：{self.model}；压缩时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        )
        summary = self._summarize(transcript, chat_fn, archive_id, verbose, printer)
        if not summary.strip():
            raise CompactError("模型没有返回摘要内容，请重试 /compact。")

        when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note = ARCHIVE_NOTE.format(when=when, archive_id=archive_id)
        content = SUMMARY_HEADER + summary.strip() + "\n\n---\n\n" + note

        info = {
            "id": archive_id,
            "path": str(path),
            "when": when,
            "model": self.model,
            "summary": summary.strip(),
            "chars": len(content),
            "tokens_estimate": estimate_text_tokens(content),
            "replaced": len(history),
            "before": describe_history(history),   # 本次到底压了哪些内容
            "outline": summary_outline(summary),   # 摘要保留了哪几块
            "source_chars": len(transcript),
            "source_tokens": estimate_text_tokens(transcript),
            "log_path": "",
        }
        try:                                       # 日志写失败不影响压缩本身
            info["log_path"] = str(append_compact_log(self.archive_dir / COMPACT_LOG_NAME, info))
        except OSError as e:
            info["log_error"] = str(e)

        self.reset_usage()                                     # 旧读数失效
        self.last_compact = info
        return [{"role": "user", "content": content}], info

    def _summarize(self, transcript: str, chat_fn, archive_id: str,
                   verbose: bool, printer) -> str:
        """一次塞得进窗口就一次压；塞不进就分片压缩再汇总。"""
        budget = int(self.window * 0.55)          # 给摘要模型的输入预算（留出输出空间）
        if estimate_text_tokens(transcript) <= budget:
            if verbose:
                printer("  🧠 调用 LLM 生成上下文摘要…")
            return chat_fn(COMPACT_PROMPT, transcript)

        chunks = split_by_tokens(transcript, int(self.window * 0.40))
        if verbose:
            printer(f"  🧠 历史较长，分 {len(chunks)} 片压缩后再汇总…")
        partials = []
        for i, chunk in enumerate(chunks, 1):
            if verbose:
                printer(f"     第 {i}/{len(chunks)} 片…")
            part = chat_fn(CHUNK_PROMPT, f"（第 {i}/{len(chunks)} 片）\n\n{chunk}")
            if part.strip():
                partials.append(f"#### 片段 {i}\n{part.strip()}")
        if not partials:
            raise CompactError("分片压缩没有产生任何内容，请重试。")
        merged = f"以下是同一段历史对话的 {len(partials)} 个片段摘要（原始记录已归档为 {archive_id}），请汇总：\n\n" + "\n\n".join(partials)
        return chat_fn(COMPACT_PROMPT, merged)
