"""工具包。

新增一个工具的做法：
1. 在本目录新建 ``<tool_name>.py``；
2. 定义 ``TOOL_NAME``、``TOOL_DESCRIPTION``，实现 ``register(server)``；
3. 回到本文件，import 它的 ``register`` 并在 ``register_tools`` 里加一行。

工具清单：
- ``getDate``     读本机 date 命令，返回当前日期时间
- ``isleapyear``  用 Python 代码判断年份是否闰年
- 文件操作组（``file_ops.py``）：
  ``get_cwd`` / ``list_files`` / ``get_file_type`` / ``read_file`` /
  ``create_file`` / ``update_file``
"""

from __future__ import annotations

from . import file_ops
from .get_date import register as register_get_date
from .is_leap_year import register as register_is_leap_year

__all__ = ["register_tools"]


def register_tools(server) -> list[str]:
    """把全部工具注册到 ``server``，返回已注册的工具名。"""
    register_get_date(server)
    register_is_leap_year(server)
    names = ["getDate", "isleapyear"]
    names.extend(file_ops.register(server))
    return names
