# -*- coding: utf-8 -*-
"""officeCli —— 封装 officecli 的 Function Calling 工具（.docx / .xlsx / .pptx）。

为什么单独做一个工具而不是让 LLM 用 RunCli 拼路径：
1. officecli 会自更新，可执行文件会在 skills 根目录与 ``OfficeCli_#SULP#_xxx`` 之间搬家，
   写死路径必然失效 —— 这里每次调用前自动定位（缓存 + mtime 校验）；
2. 参数用列表传递，避免中文路径、含空格路径在 shell 里被拆开；
3. 固定超时与输出截断，返回结构化 JSON，方便 LLM 判断下一步。

定位顺序：环境变量 OFFICECLI_EXE → 技能根目录递归搜索（取最新）→ 程序目录。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

EXE_NAME = "officecli-win-x64.exe"
TIMEOUT = 90          # 大文档处理可能较慢
MAX_CHARS = 6000      # stdout / stderr 各自上限

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "officeCli",
        "description": (
            "用 officecli 读写 Office 文档（.docx/.xlsx/.pptx），无需安装 Office。"
            "args 是命令参数列表，例如 ['view', 'D:/x/报告.docx', 'outline']、"
            "['create', 'D:/x/新建.docx']、"
            "['add', 'D:/x/新建.docx', '/body', '--type', 'paragraph', '--prop', 'text=你好']。"
            "不确定元素/属性名时先查帮助：['help', 'docx', 'paragraph']。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "参数列表（不含程序名），按顺序传给 officecli",
                },
                "cwd": {
                    "type": "string",
                    "description": "可选，工作目录（处理相对路径时用）；默认当前目录",
                },
            },
            "required": ["args"],
        },
    },
}

_EXE_CACHE: Path | None = None

# 常见报错 → 处置建议（照着做基本能一次修好，避免 LLM 反复试错）
_HINT_RULES: list[tuple[str, str]] = [
    (
        r"currently opened by a resident process",
        "该文件被 officecli 常驻进程占用：先执行 ['close', '<文件>'] 再操作；"
        "只是想新增内容时根本不需要重新 create。",
    ),
    (
        r"Unknown element type '(\w+)'",
        "--type 只接受 paragraph / run / table / row / cell / picture / chart 等元素类型；"
        "标题不是一种元素，用 ['add', 文件, '/body', '--type', 'paragraph', '--prop', 'text=标题', "
        "'--prop', 'style=Heading1']。",
    ),
    (
        r"[Ff]ile already exists",
        "文件已存在，create 只能新建：改个文件名，或直接对现有文件用 add / set。",
    ),
    (
        r"No such file|does not exist|cannot find",
        "文件路径不存在：先用绝对路径确认目录，再执行 create 新建。",
    ),
    (
        r"Property .* not (found|supported)|Unknown property",
        "属性名不对：先执行 ['help', '<格式>', '<元素>'] 查准确属性名，不要猜。",
    ),
]


def _hint_for(stderr: str, stdout: str) -> str | None:
    text = f"{stderr}\n{stdout}"
    for pattern, hint in _HINT_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return hint
    return None


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def find_officecli(search_roots: list[Path] | None = None) -> Path | None:
    """定位 officecli 可执行文件（自带缓存，文件被自更新移走后会自动重新找）。"""
    global _EXE_CACHE
    if _EXE_CACHE is not None and _EXE_CACHE.is_file():
        return _EXE_CACHE

    env = os.environ.get("OFFICECLI_EXE")
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            _EXE_CACHE = p
            return p

    roots = [r for r in (search_roots or []) if r and Path(r).is_dir()]
    roots += [Path(__file__).resolve().parent, Path.cwd()]
    best: Path | None = None
    for root in roots:
        try:
            for hit in root.rglob(EXE_NAME):
                if hit.is_file() and (best is None or hit.stat().st_mtime > best.stat().st_mtime):
                    best = hit
        except OSError:
            continue
    _EXE_CACHE = best
    return best


def _truncate(text: str, label: str) -> str:
    if text and len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n...[{label}过长已截断：原始 {len(text)} 字符]"
    return text or ""


def execute_tool(arguments: dict, search_roots: list[Path] | None = None) -> str:
    """执行 officecli，返回 JSON 字符串作为 role=tool 消息。"""
    global _EXE_CACHE
    raw_args = arguments.get("args")
    if isinstance(raw_args, str):                 # 容错：模型偶尔直接给字符串
        raw_args = [raw_args]
    args = [str(a) for a in (raw_args or []) if str(a) != ""]
    if not args:
        return _dump({
            "error": "缺少必填参数 args",
            "hint": "例如 [\"help\"]、[\"view\", \"D:/x/报告.docx\", \"outline\"]",
        })

    exe = find_officecli(search_roots)
    if exe is None:
        return _dump({
            "error": f"未找到 {EXE_NAME}，请确认 officecli 已放到技能目录，"
                     f"或设置环境变量 OFFICECLI_EXE 指向它",
        })

    cwd = arguments.get("cwd")
    workdir = str(cwd) if cwd and Path(str(cwd)).is_dir() else None

    try:
        proc = subprocess.run(
            [str(exe)] + args,
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            cwd=workdir,
        )
    except FileNotFoundError:
        _EXE_CACHE = None                          # 缓存失效，下次重新定位
        return _dump({"error": f"无法启动 officecli（{exe}），已清除缓存等待重新定位"})
    except subprocess.TimeoutExpired:
        return _dump({"error": f"命令执行超过 {TIMEOUT} 秒，已强制终止", "args": args})
    except OSError as e:
        return _dump({"error": f"启动进程失败：{e}", "args": args})

    payload = {
        "exe": str(exe),
        "args": args,
        "stdout": _truncate(proc.stdout, "stdout"),
        "stderr": _truncate(proc.stderr, "stderr"),
        "exit_code": proc.returncode,
    }
    if proc.returncode != 0:
        payload["hint"] = _hint_for(proc.stderr, proc.stdout) or (
            "命令返回非 0：检查文件路径、参数拼写；不确定时先执行 [\"help\"]"
        )
    return _dump(payload)
