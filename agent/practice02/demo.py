"""practice02 演示客户端：用真实 MCP 客户端（stdio）连上 server.py，把过程打印出来。

运行：
    .venv\\Scripts\\python.exe demo.py

先自动演示全部 11 个工具（握手 → 工具清单 → getDate → 文件操作全链路 → isleapyear），
之后进入「命令>」交互模式，可以手动调任意工具，输入 help 看命令表。
"""

from __future__ import annotations

import asyncio
import shlex
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent
LINE = "=" * 62

HELP = """\
【命令表】自动演示结束了，下面可以自己动手调任意工具：
  pwd                       当前工作目录            → get_cwd
  date                      当前日期时间            → getDate
  leap 2024                 判断是否闰年            → isleapyear
  ls [目录]                 列出目录内容            → list_files
  type <文件>               查看文件类型            → get_file_type
  cat <文件>                读取文本内容            → read_file
  mkdir <目录>              新建目录                → create_dir
  new <目录> <文件名> [内容]  新建文件                → create_file
  write <文件> <内容>        覆盖写入                → update_file
  append <文件> <内容>       追加写入                → update_file
  rm <文件>                 删除文件                → delete_file
  rmdir <目录>              删除目录（含内容）       → delete_dir
  help                      再看一遍这份命令表
  直接回车 / exit           退出

路径带空格时用双引号包住，例如：cat "D:\\my dir\\a.txt"\
"""


def text_of(result) -> str:
    """从 CallToolResult 里取出文本内容。"""
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts) if parts else str(result)


def split_args(raw: str) -> list[str]:
    """按 shell 习惯切分参数，保留 Windows 反斜杠路径，并去掉外层引号。"""
    try:
        parts = shlex.split(raw, posix=False)
    except ValueError:
        parts = raw.split()
    out = []
    for p in parts:
        if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
            p = p[1:-1]
        out.append(p)
    return out


def build_call(name: str, args: list[str]) -> tuple[str, dict]:
    """把一行命令翻译成 (工具名, 参数)；用法不对时抛 ValueError 带提示。"""
    if name in ("pwd", "cwd"):
        return "get_cwd", {}
    if name in ("date", "getdate"):
        return "getDate", {}

    if name in ("leap", "isleapyear", "year"):
        if len(args) != 1 or not args[0].isdigit() or not 1 <= int(args[0]) <= 9999:
            raise ValueError("用法：leap 2024（年份 1-9999）")
        return "isleapyear", {"year": int(args[0])}

    if name in ("ls", "list", "dir"):
        paths = [a for a in args if a != "-r"]
        return "list_files", {"path": paths[0] if paths else ".", "recursive": "-r" in args}

    if name in ("type", "ftype", "filetype"):
        if not args:
            raise ValueError("用法：type <文件路径>")
        return "get_file_type", {"path": args[0]}

    if name in ("cat", "read"):
        if not args:
            raise ValueError("用法：cat <文件路径>")
        return "read_file", {"path": args[0]}

    if name in ("mkdir", "md"):
        if not args:
            raise ValueError("用法：mkdir <目录路径>")
        return "create_dir", {"directory": args[0]}

    if name in ("new", "create", "touch"):
        if len(args) < 2:
            raise ValueError("用法：new <目录> <文件名> [内容]")
        return "create_file", {
            "directory": args[0],
            "filename": args[1],
            "content": " ".join(args[2:]),
        }

    if name in ("write", "edit", "overwrite"):
        if not args:
            raise ValueError("用法：write <文件路径> <新内容>")
        return "update_file", {
            "path": args[0],
            "content": " ".join(args[1:]),
            "mode": "overwrite",
        }

    if name == "append":
        if not args:
            raise ValueError("用法：append <文件路径> <要追加的内容>")
        return "update_file", {
            "path": args[0],
            "content": " ".join(args[1:]),
            "mode": "append",
        }

    if name in ("rm", "del"):
        if not args:
            raise ValueError("用法：rm <文件路径>")
        return "delete_file", {"path": args[0]}

    if name in ("rmdir", "rmrf"):
        if not args:
            raise ValueError("用法：rmdir <目录路径>（会连同内容一起删）")
        return "delete_dir", {"path": args[0], "recursive": True}

    raise ValueError("未知命令：%s（输入 help 看命令表）" % name)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "server.py")],
        cwd=str(HERE),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()

            print(LINE)
            print("已连上 MCP 服务：%s   协议版本：%s"
                  % (init.server_info.name or "?", init.protocol_version))
            print(LINE)

            listed = await session.list_tools()
            print("\n【工具清单】共 %d 个" % len(listed.tools))
            for t in listed.tools:
                first = (t.description or "").splitlines()[0]
                print("  · %-12s %s" % (t.name, first))

            print("\n【调用 getDate】")
            got = await session.call_tool("getDate", {})
            print("  当前时间 -> %s" % text_of(got))

            # 文件操作组：全部在临时沙盒里做，不碰项目文件
            sandbox = Path(tempfile.mkdtemp(prefix="practice02_"))
            demo_file = sandbox / "sub" / "demo.txt"
            print("\n【文件操作组】沙盒目录：%s" % sandbox)
            steps = [
                ("get_cwd", {}),
                ("create_dir", {"directory": str(sandbox / "sub")}),
                ("create_file", {"directory": str(sandbox / "sub"), "filename": "demo.txt",
                                 "content": "第一行\n第二行\n"}),
                ("get_file_type", {"path": str(demo_file)}),
                ("read_file", {"path": str(demo_file)}),
                ("update_file", {"path": str(demo_file), "content": "追加的一行", "mode": "append"}),
                ("read_file", {"path": str(demo_file)}),
                ("list_files", {"path": str(sandbox), "recursive": True}),
                ("delete_file", {"path": str(demo_file)}),
                ("delete_dir", {"path": str(sandbox)}),
            ]
            for tool_name, args in steps:
                res = await session.call_tool(tool_name, args)
                print("\n  · %s" % tool_name)
                for line in text_of(res).splitlines()[:7]:
                    print("    " + line)

            print("\n【调用 isleapyear】")
            interactive = sys.stdin is not None and sys.stdin.isatty()
            fixed = [2024, 2023, 1900, 2000]
            for year in fixed:
                r = await session.call_tool("isleapyear", {"year": year})
                print("  %d -> %s" % (year, text_of(r)))

            if not interactive:
                return

            print("\n" + LINE)
            print(HELP)
            print(LINE)
            while True:
                try:
                    raw = await asyncio.to_thread(input, "命令> ")
                except (EOFError, KeyboardInterrupt):
                    break
                raw = raw.strip()
                if not raw or raw.lower() in ("exit", "quit", "q"):
                    break
                if raw.lower() in ("help", "?", "h"):
                    print(HELP)
                    continue
                # 纯数字 = 直接当闰年判断
                if raw.isdigit():
                    r = await session.call_tool("isleapyear", {"year": int(raw)})
                    print("  " + text_of(r))
                    continue

                name, _, rest = raw.partition(" ")
                try:
                    tool_name, args = build_call(name.lower(), split_args(rest))
                except ValueError as exc:
                    print("  %s" % exc)
                    continue

                res = await session.call_tool(tool_name, args)
                body = text_of(res)
                print("  [%s]" % tool_name)
                for line in body.splitlines()[:15]:
                    print("  " + line)

            print("\n再见。")


if __name__ == "__main__":
    asyncio.run(main())
