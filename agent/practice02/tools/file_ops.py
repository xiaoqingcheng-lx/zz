"""本地文件操作工具组。

九个工具：
- ``get_cwd``       取当前工作目录
- ``list_files``    列目录内容（可选递归）
- ``get_file_type`` 判断文件类型（MIME + 是否纯文本）
- ``read_file``     读文件内容（限纯文本、限大小）
- ``create_file``   在指定目录按文件名新建文件
- ``update_file``   改写/追加文件内容（只支持纯文本）
- ``create_dir``    新建目录（自动补父级）
- ``delete_dir``    删除目录（可删非空）
- ``delete_file``   删除文件

约定：读操作不设路径限制；写/删操作会拒绝系统关键目录、
拒绝删除磁盘根与当前工作目录，并拒绝把二进制文件当文本处理。
"""

from __future__ import annotations

import mimetypes
import os
import shutil
from pathlib import Path
from typing import Annotated

from pydantic import Field

MAX_READ_BYTES = 200_000     # 单次读取上限，防止把大文件灌进上下文
MAX_LIST_ITEMS = 2_000       # 列目录条目上限
MAX_WRITE_BYTES = 1_000_000  # 单次写入上限

# 常见纯文本后缀：命中即可直接编辑
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".py", ".pyi", ".ipynb", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".html", ".htm", ".css", ".scss", ".vue", ".xml", ".svg",
    ".sh", ".bash", ".bat", ".cmd", ".ps1",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".java", ".go", ".rs", ".sql", ".php", ".rb",
}

# 写操作拒绝落在这些目录（小写比较、前缀匹配）
_PROTECTED_PREFIXES = tuple(
    str(Path(os.environ.get(var, "C:/__none__"))).lower()
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")
)


# ---------------------------------------------------------------- 公共小工具

def _resolve(raw: str) -> Path:
    """展开 ~ 与环境变量，转成绝对路径。"""
    return Path(os.path.expandvars(os.path.expanduser(raw.strip()))).resolve()


def _looks_binary(data: bytes) -> bool:
    """粗判二进制：含 NUL 字节，或可打印字符比例过低。"""
    sample = data[:4096]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    printable = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b < 127 or b >= 128)
    return printable / len(sample) < 0.90


def _decode(data: bytes) -> tuple[str, str]:
    """按 UTF-8 → GBK 的顺序解码，返回 (文本, 实际编码)。"""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace"), "utf-8(部分替换)"


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return ("%d %s" % (size, unit)) if unit == "B" else ("%.1f %s" % (size, unit))
        size /= 1024
    return "%.1f GB" % size


def _guard_write(target: Path) -> str | None:
    """写操作的安全检查；返回非 None 表示拒绝原因。"""
    low = str(target).lower()
    for prefix in _PROTECTED_PREFIXES:
        if prefix and low.startswith(prefix):
            return "拒绝操作系统目录：%s" % prefix
    return None


def _guard_delete(target: Path) -> str | None:
    """删除操作的安全检查；返回非 None 表示拒绝原因。"""
    denied = _guard_write(target)
    if denied:
        return denied
    if target.parent == target:
        return "拒绝删除磁盘根目录：%s" % target
    try:
        cwd = Path(os.getcwd()).resolve()
    except OSError:
        cwd = None
    if cwd and (target == cwd or target in cwd.parents):
        return "拒绝删除当前工作目录或其上级目录：%s" % target
    return None


# ---------------------------------------------------------------- 1. 工作目录

def _register_get_cwd(server) -> None:
    @server.tool(
        name="get_cwd",
        description="""\
获取当前进程的工作目录（绝对路径）。

【适用场景】不确定相对路径以哪个目录为基准时，先调它。

【参数】无。

【返回值】一行绝对路径，例如 `D:\\大语言模型\\agent\\practice02`。""",
    )
    async def get_cwd() -> str:
        """返回当前工作目录。"""
        return os.getcwd()


# ---------------------------------------------------------------- 2. 列目录

def _register_list_files(server) -> None:
    @server.tool(
        name="list_files",
        description="""\
列出指定目录下的文件与子目录。

【参数】
- path       目录路径，默认 `.`（当前工作目录）
- recursive  是否递归列出所有层级，默认 false（只看一级）

【返回值】
首行是目录绝对路径与统计，其后每行一项：
`[目录] tools` 或 `[文件] server.py    5.9 KB`。
递归模式最多返回 2000 项，超出会截断并提示。

【不适用】要读文件内容请用 read_file。""",
    )
    async def list_files(
        path: Annotated[str, Field(description="要列出的目录路径，默认当前工作目录。")] = ".",
        recursive: Annotated[bool, Field(description="是否递归列出所有层级，默认只列一级。")] = False,
    ) -> str:
        """列出目录内容。"""
        target = _resolve(path)
        if not target.exists():
            return "列出失败：目录不存在 → %s" % target
        if not target.is_dir():
            return "列出失败：这不是目录 → %s" % target

        if recursive:
            entries = list(target.rglob("*"))
        else:
            entries = list(target.iterdir())

        entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
        truncated = len(entries) > MAX_LIST_ITEMS
        shown = entries[:MAX_LIST_ITEMS]

        dirs = sum(1 for p in shown if p.is_dir())
        files = len(shown) - dirs
        lines = [
            "目录：%s" % target,
            "共 %d 项（%d 个目录 / %d 个文件）%s"
            % (len(entries), dirs, files, "，仅显示前 %d 项" % MAX_LIST_ITEMS if truncated else ""),
            "",
        ]
        for p in shown:
            rel = p.relative_to(target)
            if p.is_dir():
                lines.append("[目录] %s" % rel)
            else:
                try:
                    size = _human_size(p.stat().st_size)
                except OSError:
                    size = "?"
                lines.append("[文件] %-50s %10s" % (rel, size))
        return "\n".join(lines)


# ---------------------------------------------------------------- 3. 文件类型

def _register_get_file_type(server) -> None:
    @server.tool(
        name="get_file_type",
        description="""\
判断指定文件是什么类型。

【判断依据】
后缀 → MIME 类型（mimetypes 表），再读前 4KB 判断是否纯文本。

【参数】
- path  文件路径

【返回值】
多行说明：绝对路径、后缀、MIME 类型、大小、是否纯文本、能否用 update_file 编辑。
例：
```
路径：D:\\tmp\\a.md
后缀：.md
MIME：text/markdown
大小：1.2 KB
纯文本：是
可编辑：是
```""",
    )
    async def get_file_type(
        path: Annotated[str, Field(description="要判断的文件路径。")],
    ) -> str:
        """返回文件类型信息。"""
        target = _resolve(path)
        if not target.exists():
            return "判断失败：路径不存在 → %s" % target
        if target.is_dir():
            return "判断失败：这是目录 → %s" % target

        suffix = target.suffix.lower() or "（无后缀）"
        mime, encoding = mimetypes.guess_type(target.name)
        if mime is None:
            mime = "application/octet-stream（未知）"

        try:
            with target.open("rb") as f:
                head = f.read(4096)
            size = target.stat().st_size
        except OSError as exc:
            return "判断失败：读取不了 → %s" % exc

        binary = _looks_binary(head)
        is_text = not binary
        editable = is_text

        lines = [
            "路径：%s" % target,
            "后缀：%s" % suffix,
            "MIME：%s%s" % (mime, "（编码 %s）" % encoding if encoding else ""),
            "大小：%s（%d 字节）" % (_human_size(size), size),
            "纯文本：%s" % ("是" if is_text else "否"),
            "可编辑：%s" % ("是（update_file 可用）" if editable else "否（二进制文件不支持编辑）"),
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------- 4. 读文件

def _register_read_file(server) -> None:
    @server.tool(
        name="read_file",
        description="""\
读取指定文件的文本内容。

【参数】
- path       文件路径
- max_bytes  最多读多少字节，默认 200000（约 200KB）

【限制】
只读纯文本；二进制文件（含 NUL 字节）直接拒绝，避免乱码刷屏。
文件大于 max_bytes 时只返回开头部分并注明截断。
编码按 UTF-8（含 BOM）→ GBK 顺序尝试。

【返回值】
文件内容原文（不额外包 JSON）。取不到时以 `读取失败：` 开头。""",
    )
    async def read_file(
        path: Annotated[str, Field(description="要读取的文件路径。")],
        max_bytes: Annotated[int, Field(ge=1, le=MAX_READ_BYTES, description="最多读取字节数，上限 200000。")] = MAX_READ_BYTES,
    ) -> str:
        """读取文件文本内容。"""
        target = _resolve(path)
        if not target.exists():
            return "读取失败：文件不存在 → %s" % target
        if target.is_dir():
            return "读取失败：这是目录，列目录请用 list_files → %s" % target

        try:
            total = target.stat().st_size
            with target.open("rb") as f:
                data = f.read(max_bytes)
        except OSError as exc:
            return "读取失败：%s" % exc

        if _looks_binary(data):
            return "读取失败：%s 看起来是二进制文件（大小 %s），不支持按文本读取。" % (
                target.name, _human_size(total))

        text, encoding = _decode(data)
        if total > len(data):
            text += "\n\n……（已截断：文件共 %s，本次只读前 %d 字节）" % (_human_size(total), len(data))
        return text


# ---------------------------------------------------------------- 5. 建文件

def _register_create_file(server) -> None:
    @server.tool(
        name="create_file",
        description="""\
在指定目录下按给定文件名新建一个文本文件。

【参数】
- directory  目标目录，不存在会自动逐级创建
- filename   文件名（只能是文件名，不能带路径分隔符）
- content    初始内容，默认空

【行为】
文件已存在时报错并提示改用 update_file，**不会覆盖**已有文件。
写入编码固定 UTF-8（无 BOM）。

【返回值】
成功时给出完整路径与实际写入字节数；失败以 `创建失败：` 开头。""",
    )
    async def create_file(
        directory: Annotated[str, Field(description="目标目录，不存在会自动创建。")],
        filename: Annotated[str, Field(min_length=1, description="文件名，不能带路径分隔符。")],
        content: Annotated[str, Field(description="初始内容，默认空。")] = "",
    ) -> str:
        """新建文件。"""
        name = filename.strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return "创建失败：文件名不合法 → %r" % filename

        folder = _resolve(directory)
        if folder.exists() and not folder.is_dir():
            return "创建失败：%s 已存在且不是目录。" % folder
        target = folder / name

        denied = _guard_write(target)
        if denied:
            return "创建失败：%s" % denied
        if target.exists():
            return "创建失败：%s 已存在。要改内容请用 update_file。" % target
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return "创建失败：内容超过 %s 上限。" % _human_size(MAX_WRITE_BYTES)

        try:
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")
        except OSError as exc:
            return "创建失败：%s" % exc

        return "已创建：%s（写入 %d 字节）" % (target, len(content.encode("utf-8")))


# ---------------------------------------------------------------- 6. 改文件

def _register_update_file(server) -> None:
    @server.tool(
        name="update_file",
        description="""\
编辑一个已存在的纯文本文件的内容。

【参数】
- path     文件路径
- content  新内容（整体替换）或要追加的内容
- mode     `overwrite`（默认，整体替换）或 `append`（追加到末尾）

【限制】
只支持纯文本：后缀不在常见文本白名单里、或内容检测为二进制时拒绝，
避免把图片/压缩包之类写坏。
写入编码固定 UTF-8（无 BOM）。

【返回值】
成功时给出路径、模式与写入字节数；失败以 `编辑失败：` 开头。""",
    )
    async def update_file(
        path: Annotated[str, Field(description="要编辑的文件路径。")],
        content: Annotated[str, Field(description="新的完整内容，或要追加的内容。")],
        mode: Annotated[str, Field(pattern="^(overwrite|append)$", description="overwrite 覆盖 / append 追加。")] = "overwrite",
    ) -> str:
        """编辑纯文本文件。"""
        target = _resolve(path)
        if not target.exists():
            return "编辑失败：文件不存在 → %s（新建请用 create_file）" % target
        if target.is_dir():
            return "编辑失败：这是目录 → %s" % target

        denied = _guard_write(target)
        if denied:
            return "编辑失败：%s" % denied

        payload = content.encode("utf-8")
        if len(payload) > MAX_WRITE_BYTES:
            return "编辑失败：内容超过 %s 上限。" % _human_size(MAX_WRITE_BYTES)

        suffix = target.suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            try:
                with target.open("rb") as f:
                    head = f.read(4096)
            except OSError as exc:
                return "编辑失败：读不了原文件 → %s" % exc
            if _looks_binary(head):
                return "编辑失败：%s 是二进制文件（后缀 %s），只支持纯文本。" % (
                    target.name, suffix or "无")

        try:
            if mode == "append":
                existing = ""
                if target.stat().st_size:
                    existing = target.read_bytes().decode("utf-8", "replace")
                sep = "" if (not existing or existing.endswith("\n")) else "\n"
                target.write_text(existing + sep + content, encoding="utf-8", newline="")
            else:
                target.write_text(content, encoding="utf-8", newline="")
        except OSError as exc:
            return "编辑失败：%s" % exc

        action = "追加" if mode == "append" else "覆盖"
        total = target.stat().st_size
        return "已%s：%s（本次写入 %d 字节，文件现有 %s）" % (
            action, target, len(payload), _human_size(total))


# ---------------------------------------------------------------- 7. 建目录

def _register_create_dir(server) -> None:
    @server.tool(
        name="create_dir",
        description="""\
创建一个新目录（父目录不存在时会一并创建）。

【参数】
- directory  要创建的目录路径

【行为】
目录已存在时不报错也不改动，直接返回"已存在"；
若同名路径已存在但是个文件，则报错。

【返回值】
成功：`已创建目录：<绝对路径>`；否则以 `创建失败：` 开头。""",
    )
    async def create_dir(
        directory: Annotated[str, Field(min_length=1, description="要创建的目录路径，父目录会自动创建。")],
    ) -> str:
        """新建目录。"""
        target = _resolve(directory)
        denied = _guard_write(target)
        if denied:
            return "创建失败：%s" % denied
        if target.exists():
            if target.is_dir():
                return "目录已存在，无需创建：%s" % target
            return "创建失败：%s 已存在且是文件。" % target

        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return "创建失败：%s" % exc
        return "已创建目录：%s" % target


# ---------------------------------------------------------------- 8. 删目录

def _register_delete_dir(server) -> None:
    @server.tool(
        name="delete_dir",
        description="""\
删除一个目录（可删非空目录）。

【参数】
- path       要删除的目录
- recursive  是否连同里面的内容一起删，默认 true（可删非空目录）；
             false 时只删空目录，非空会报错

【危险提示】
删除不可恢复，不经回收站。以下情况一律拒绝：
磁盘根目录、系统目录（Windows / Program Files / ProgramData）、
当前工作目录及其上级目录。

【返回值】
成功：`已删除目录：<路径>（含 N 个条目）`；否则以 `删除失败：` 开头。""",
    )
    async def delete_dir(
        path: Annotated[str, Field(min_length=1, description="要删除的目录路径。")],
        recursive: Annotated[bool, Field(description="是否连带删除目录内全部内容，默认 true。")] = True,
    ) -> str:
        """删除目录。"""
        target = _resolve(path)
        if not target.exists():
            return "删除失败：目录不存在 → %s" % target
        if not target.is_dir():
            return "删除失败：这是文件，请用 delete_file → %s" % target

        denied = _guard_delete(target)
        if denied:
            return "删除失败：%s" % denied

        try:
            items = sum(1 for _ in target.rglob("*"))
        except OSError:
            items = -1

        try:
            if recursive:
                shutil.rmtree(target)
            else:
                target.rmdir()          # 非空会抛 OSError
        except OSError as exc:
            if not recursive:
                return ("删除失败：目录非空（含 %s 个条目）。确要连内容一起删，"
                        "请把 recursive 设为 true。原错误：%s" % (items if items >= 0 else "若干", exc))
            return "删除失败：%s" % exc

        return "已删除目录：%s（含 %d 个条目）" % (target, max(items, 0))


# ---------------------------------------------------------------- 9. 删文件

def _register_delete_file(server) -> None:
    @server.tool(
        name="delete_file",
        description="""\
删除一个文件。

【参数】
- path  要删除的文件

【危险提示】
删除不可恢复，不经回收站。系统目录下的文件一律拒绝删除。

【返回值】
成功：`已删除文件：<路径>（原大小 X）`；否则以 `删除失败：` 开头。""",
    )
    async def delete_file(
        path: Annotated[str, Field(min_length=1, description="要删除的文件路径。")],
    ) -> str:
        """删除文件。"""
        target = _resolve(path)
        if not target.exists():
            return "删除失败：文件不存在 → %s" % target
        if target.is_dir():
            return "删除失败：这是目录，请用 delete_dir → %s" % target

        denied = _guard_delete(target)
        if denied:
            return "删除失败：%s" % denied

        try:
            size = _human_size(target.stat().st_size)
            target.unlink()
        except OSError as exc:
            return "删除失败：%s（文件可能正被其他程序占用）" % exc

        return "已删除文件：%s（原大小 %s）" % (target, size)


# ---------------------------------------------------------------- 注册入口

def register(server) -> list[str]:
    """把文件操作这一组工具注册到 MCPServer 上。"""
    _register_get_cwd(server)
    _register_list_files(server)
    _register_get_file_type(server)
    _register_read_file(server)
    _register_create_file(server)
    _register_update_file(server)
    _register_create_dir(server)
    _register_delete_dir(server)
    _register_delete_file(server)
    return [
        "get_cwd", "list_files", "get_file_type", "read_file",
        "create_file", "update_file",
        "create_dir", "delete_dir", "delete_file",
    ]
