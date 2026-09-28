"""工具层共享的入参模型。

文件名以下划线开头，``tools/__init__.py`` 的工具自动发现会跳过它，
因此它不会被误当成一个工具模块。

上游**出参**模型不在这里 —— 它们放在包根的 :mod:`pet_hospital_mcp.upstream`，
因为 ``rest_client`` 才是解析上游响应的地方，放这里会造成循环导入。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

__all__ = ["PET_ID_PATTERN", "PetId", "PetIdInput"]

#: Go 侧主键由 ``nextIDLocked()`` 生成，格式固定为 ``PET-%06d``（档案数超过 99 万会进位）。
#: 客户端无法指定主键，所以这个形状是上游保证的，可以拿来挡掉明显不对的参数。
PET_ID_PATTERN = r"^PET-[0-9]{1,12}$"

PetId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=PET_ID_PATTERN)]


class PetIdInput(BaseModel):
    """所有「按 id 查单只宠物」类工具共用的入参模型。

    只做**形状**校验（``PET-000001`` 这种）。形状合法但档案不存在时，
    由上游返回 404，适配器映射成 ``BACKEND_API_ERROR``（``details.status = 404``）。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    id: PetId = Field(description="宠物档案编号，形如 PET-000001。", examples=["PET-000001"])
