"""``isleapyear`` 工具：判断给定年份是不是闰年。

与 ``getDate`` 相反，这个工具的判定逻辑**全部由 Python 代码完成**：
按公历规则「能被 4 整除；但若是整百年，必须还能被 400 整除」直接计算。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

TOOL_NAME = "isleapyear"

TOOL_DESCRIPTION = """\
判断某个公历年份是闰年还是平年。

【判定规则】
能被 4 整除的是闰年；但整百年份（如 1900）必须还能被 400 整除才算闰年。
例：2024 闰年、2023 平年、1900 平年（整百但除不尽 400）、2000 闰年。

【参数】
- year  待判断的年份，1-9999 的整数。

【返回值】
判定结论文本，含该年天数与 2 月天数，例如：
`2024 年是闰年：全年 366 天，2 月有 29 天。`
"""

MIN_YEAR = 1
MAX_YEAR = 9999


def is_leap_year(year: int) -> bool:
    """公历闰年判定。"""
    if year % 4 != 0:          # 不能被 4 整除，一定是平年
        return False
    if year % 100 != 0:        # 能被 4 整除且不是整百年，是闰年
        return True
    return year % 400 == 0     # 整百年：能被 400 整除才是闰年


def leap_year_text(year: int) -> str:
    """把判定结果组织成一句人话。"""
    if is_leap_year(year):
        return f"{year} 年是闰年：全年 366 天，2 月有 29 天。"
    return f"{year} 年是平年：全年 365 天，2 月有 28 天。"


def register(server) -> None:
    """把 ``isleapyear`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def isleapyear(
        year: Annotated[int, Field(ge=MIN_YEAR, le=MAX_YEAR, description="待判断的年份，1-9999。")],
    ) -> str:
        """判断该年份是否为闰年。"""
        return leap_year_text(year)
