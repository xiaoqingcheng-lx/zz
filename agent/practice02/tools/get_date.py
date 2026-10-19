"""``getDate`` 工具：读取当前电脑的日期与时间。

实现要点（按练习要求）：**不写 Python 的日期计算逻辑**，而是调用本机的
``date`` 命令取结果，本文件只负责「拼命令 / 跑命令 / 读输出」。

Windows 上 ``date`` 是 cmd 的内建命令，没有同名 exe，所以按下面的顺序找：
1. PATH 里的 ``date``（Git Bash / MSYS2 / Cygwin / Linux / macOS 都有）；
2. 常见 Git for Windows 安装目录下的 ``usr/bin/date.exe``；
3. 都找不到时退回 ``cmd /c date /t`` 与 ``cmd /c time /t`` 这两条内建命令。
三条路都是「调本地命令」，没有一处自己算时间。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

TOOL_NAME = "getDate"

TOOL_DESCRIPTION = """\
获取当前电脑的本地日期与时间（年月日、时分秒、星期、时区）。

【实现方式】
调用本机 `date` 命令取结果，不做自定义的日期计算。

【适用场景】
- 「现在几点」「今天几号」「今天是星期几」
- 需要把当前时间作为上下文（例如算某件事距今多久）

【参数】
无。

【返回值】
形如 `2026-10-19 09:59:38 Monday +0800` 的一行文本；
取不到时返回以 `获取失败：` 开头的错误说明。
"""

# date 命令的输出格式（GNU date 语法）
_FORMAT = "+%Y-%m-%d %H:%M:%S %A %z"
_TIMEOUT = 10          # 秒

# Windows 上没有独立 date.exe 时的常见安装位置（相对各环境变量根目录）
_GIT_DATE_HINTS = (
    ("ProgramFiles", "Git/usr/bin/date.exe"),
    ("ProgramFiles(x86)", "Git/usr/bin/date.exe"),
    ("ProgramW6432", "Git/usr/bin/date.exe"),
    ("LOCALAPPDATA", "Programs/Git/usr/bin/date.exe"),
    ("USERPROFILE", "scoop/apps/git/current/usr/bin/date.exe"),
)


def _hide_window() -> int:
    """Windows 下别弹出黑框（服务被 GUI 客户端拉起时尤其明显）。"""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def _run(argv: list[str], encoding: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
        timeout=_TIMEOUT,
        creationflags=_hide_window(),
    )


def _find_date_exe() -> str | None:
    """找一个能直接执行的 date 程序；找不到返回 None。"""
    found = shutil.which("date")
    if found:
        return found

    if os.name == "nt":
        for var, rel in _GIT_DATE_HINTS:
            root = os.environ.get(var)
            if not root:
                continue
            candidate = Path(root) / rel
            if candidate.is_file():
                return str(candidate)
    return None


def _via_date_command() -> str | None:
    """走 date 命令本身。"""
    exe = _find_date_exe()
    if not exe:
        return None
    try:
        proc = _run([exe, _FORMAT], "utf-8")
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def _via_windows_builtin() -> str | None:
    """Windows 兜底：cmd 内建的 date /t + time /t。"""
    if os.name != "nt":
        return None
    try:
        d = _run(["cmd", "/c", "date /t"], "gbk")
        t = _run(["cmd", "/c", "time /t"], "gbk")
    except (OSError, subprocess.SubprocessError):
        return None
    date_part = d.stdout.strip()
    time_part = t.stdout.strip()
    if date_part and time_part:
        return f"{date_part} {time_part}"
    return None


def current_datetime_text() -> str:
    """当前日期时间文本；两条路都失败时返回错误说明。"""
    text = _via_date_command()
    if text:
        return text
    text = _via_windows_builtin()
    if text:
        return text
    return "获取失败：本机找不到 date 命令（PATH 与常见 Git 安装目录都没有，cmd 内建命令也不可用）。"


def register(server) -> None:
    """把 ``getDate`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_date() -> str:
        """返回当前电脑的日期与时间。"""
        return current_datetime_text()
