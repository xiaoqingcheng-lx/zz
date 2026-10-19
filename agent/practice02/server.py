"""practice02：MCP 练习服务。

对外提供两组工具（共 11 个）：
- 时间与日期：``getDate``（调本机 date 命令）、``isleapyear``（Python 计算闰年）
- 本地文件操作：``get_cwd``、``list_files``、``get_file_type``、``read_file``、
  ``create_file``、``update_file``、``create_dir``、``delete_dir``、``delete_file``

运行（stdio 传输，供 MCP 客户端拉起）：
    .venv\\Scripts\\python.exe server.py
"""

from __future__ import annotations

from mcp.server import MCPServer

from tools import register_tools

SERVER_NAME = "practice02"

INSTRUCTIONS = """\
这是一个练习用的小服务，工具分两组：

【时间与日期】
- `getDate`     读取当前电脑的日期与时间（内部调用本机 date 命令）。
- `isleapyear`  判断某一年是不是闰年（按公历规则用代码计算）。

【本地文件操作】
- `get_cwd`        当前工作目录，不确定相对路径基准时先调它。
- `list_files`     列目录内容，可选递归；递归默认关闭。
- `get_file_type`  判断文件类型（后缀 / MIME / 是否纯文本）。
- `read_file`      读文本内容，二进制文件会被拒绝。
- `create_file`    在指定目录按文件名新建文件，已存在则报错不覆盖。
- `update_file`    改写或追加纯文本内容，二进制文件会被拒绝。
- `create_dir`     新建目录，父级不存在会自动补。
- `delete_dir`     删除目录，默认可删非空（recursive=true）。
- `delete_file`    删除文件。

删除不可恢复。系统目录、磁盘根、当前工作目录及上级一律拒绝。

建议顺序：先用 get_cwd 确认位置 → list_files 看有什么 →
get_file_type 判断能否当文本处理 → read_file / update_file 读写。
"""


def build_server() -> MCPServer:
    """装配服务并注册全部工具。"""
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)
    register_tools(server)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
