"""``list_pet_charges`` 工具：单只宠物的消费明细（``GET /api/v1/pets/{id}/charges``）。

阶段二新增工具。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..errors import ErrorCode, ToolFailure, failure
from ..logging_config import get_logger
from ..rest_client import PetHospitalClient
from ..upstream import PetChargesData
from ._shared import PetId, PetIdInput

__all__ = ["TOOL_NAME", "TOOL_DESCRIPTION", "INPUT_MODEL", "register"]

logger = get_logger("tools.list_pet_charges")

TOOL_NAME = "list_pet_charges"

INPUT_MODEL = PetIdInput

TOOL_DESCRIPTION = """\
读取**某一只**宠物的消费明细（每一笔收费）及按收费分类聚合的金额。
只读查询，不修改任何数据。

【用途】
把「这只宠物钱花在哪了」交给模型：逐笔费用清单 + 分类小计，用于解释账单构成。

【适用场景】
- 「PET-000207 的费用明细」
- 「这只狗的钱主要花在手术还是药品上」——看 costByCategory
- 「单笔最贵的是哪一项」——在 charges 里按 amount 取最大
- 核对总花费与逐笔金额是否对得上

【不适用】跨宠物的花费筛选与排行（用 list_pets 的 min / max / sortBy）；
单只宠物的费用汇总与次均花费（用 get_pet_summary）；全医院收入（用 get_stats）。

【参数】
- id  宠物档案编号（必填），形如 PET-000001。

【返回值】
- petId            宠物档案编号
- petName          宠物姓名
- count            收费笔数
- charges          消费明细数组（无收费时为 []，不会是 null）。每笔含
                   id / item（收费项目）/ category（分类）/ amount（金额，元）/
                   doctor / date / note
- totalCost        该宠物总花费（元）
- costByCategory   按分类聚合金额（元），如 {"检查": 880.34, "药品": 159.05}

【错误码】
- VALIDATION_ERROR    id 缺失，或格式不是 "PET-" + 数字
- BACKEND_API_ERROR   编号格式合法但档案不存在（details.status = 404）；或上游返回其它失败
- BACKEND_TIMEOUT / BACKEND_UNAVAILABLE / BACKEND_INVALID_RESPONSE / INTERNAL_ERROR  见服务说明
"""


def register(server: Any, client: PetHospitalClient) -> None:
    """把 ``list_pet_charges`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def list_pet_charges(id: PetId = Field(description="宠物档案编号，形如 PET-000001。")) -> PetChargesData:
        """读取单只宠物的消费明细与分类小计。"""
        try:
            return await client.list_pet_charges(id)
        except ToolFailure as exc:
            failure(exc.code, exc.message, exc.details)
        except Exception:  # pragma: no cover - 兜底，绝不把堆栈泄漏给客户端
            logger.exception("unexpected failure while calling list_pet_charges")
            failure(ErrorCode.INTERNAL_ERROR, "适配器内部错误。")
