"""``get_pet_summary`` 工具：单只宠物的费用与就诊汇总（``GET /api/v1/pets/{id}/summary``）。

阶段二新增工具。这是四个「按 id 查」工具里信息最浓缩的一个：
把档案基本信息 + 花费分布 + 就诊时间跨度一次给全。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..errors import ErrorCode, ToolFailure, failure
from ..logging_config import get_logger
from ..rest_client import PetHospitalClient
from ..upstream import PetSummaryData
from ._shared import PetId, PetIdInput

__all__ = ["TOOL_NAME", "TOOL_DESCRIPTION", "INPUT_MODEL", "register"]

logger = get_logger("tools.get_pet_summary")

TOOL_NAME = "get_pet_summary"

INPUT_MODEL = PetIdInput

TOOL_DESCRIPTION = """\
读取**某一只**宠物的费用与就诊汇总：基本信息 + 总花费 + 就诊次数 + 收费笔数 +
按分类/按医生的金额分布 + 单笔最高收费 + 次均花费 + 首末就诊日期 + 病程文本。
只读查询，不修改任何数据。

【用途】
回答「这只宠物一共花了多少、花在哪、什么时候来过的」，比同时调
list_pet_records + list_pet_charges 更省 token。

【适用场景】
- 「PET-000207 一共花了多少钱，看过几次」
- 「这只宠物的钱是哪个医生收的」——看 costByDoctor
- 「平均每次就诊花多少」——直接读 avgCostPerVisit
- 「第一次和最近一次就诊是什么时候」——读 firstVisit / lastVisit

【不适用】逐笔费用清单（用 list_pet_charges）；逐条病历详情（用 list_pet_records）；
全医院口径的统计（用 get_stats）。

【参数】
- id  宠物档案编号（必填），形如 PET-000001。

【返回值】
- id / name / species / ownerName / ownerPhone / doctor / disease / status   档案基本信息
- totalCost        在医院总花费（元）
- visitCount       就诊次数（= 病历条数）
- chargeCount      收费笔数
- costByCategory   按收费分类聚合金额（元）
- costByDoctor     按医生聚合金额（元）
- maxSingleCharge  单笔最高收费（元）
- avgCostPerVisit  次均花费（元）= totalCost / visitCount，无病历时为 0
- firstVisit / lastVisit  首次与最近一次就诊日期
- historyText      病历纯文本摘录

【错误码】
- VALIDATION_ERROR    id 缺失，或格式不是 "PET-" + 数字
- BACKEND_API_ERROR   编号格式合法但档案不存在（details.status = 404）；或上游返回其它失败
- BACKEND_TIMEOUT / BACKEND_UNAVAILABLE / BACKEND_INVALID_RESPONSE / INTERNAL_ERROR  见服务说明

注意：返回值含主人电话，请勿在无关场合转述。
"""


def register(server: Any, client: PetHospitalClient) -> None:
    """把 ``get_pet_summary`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_pet_summary(id: PetId = Field(description="宠物档案编号，形如 PET-000001。")) -> PetSummaryData:
        """读取单只宠物的费用与就诊汇总。"""
        try:
            return await client.get_pet_summary(id)
        except ToolFailure as exc:
            failure(exc.code, exc.message, exc.details)
        except Exception:  # pragma: no cover - 兜底，绝不把堆栈泄漏给客户端
            logger.exception("unexpected failure while calling get_pet_summary")
            failure(ErrorCode.INTERNAL_ERROR, "适配器内部错误。")
