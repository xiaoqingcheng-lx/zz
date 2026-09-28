"""``get_stats`` 工具：全医院经营统计（``GET /api/v1/stats``）。

阶段二新增工具。注意这是**全医院口径**的聚合，不做任何过滤，
与 ``list_pets`` 的「过滤后结果集」口径不同。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import ErrorCode, ToolFailure, failure, validation_details
from ..logging_config import get_logger
from ..rest_client import PetHospitalClient
from ..upstream import HospitalStats

__all__ = ["TOOL_NAME", "TOOL_DESCRIPTION", "INPUT_MODEL", "GetStatsInput", "register"]

logger = get_logger("tools.get_stats")

TOOL_NAME = "get_stats"

MAX_TOP = 100


class GetStatsInput(BaseModel):
    """``get_stats`` 的严格输入模型。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    top: int = Field(
        default=5,
        ge=1,
        le=MAX_TOP,
        description=f"消费排行返回的档案条数，1-{MAX_TOP}，默认 5。",
    )


INPUT_MODEL = GetStatsInput

TOOL_DESCRIPTION = f"""\
读取宠物医院的**全医院**经营统计：档案数、病历数、收费笔数、总收入、客单价、单只最高花费、
按种类/状态/医生的分布、按医生的收入排行，以及消费排行前列的完整档案。
只读查询，不修改任何数据。

【用途】
回答「这家医院整体怎么样」，不需要先拉全量数据再自己算；聚合由上游完成。

【适用场景】
- 「医院一共多少只宠物、总收入多少」
- 「哪种宠物最多」——看 bySpecies
- 「现在有多少住院中的」——看 byStatus
- 「哪个医生接诊最多 / 收入最高」——看 byDoctor、revenueByDoctor
- 「花钱最多的几只宠物是谁」——看 topSpenders（完整档案对象）

【不适用】带过滤条件的统计（本工具是全量口径；要按条件统计请用 list_pets 的
total / totalCost 字段自己汇总）；单只宠物的费用（用 get_pet_summary）。

【参数】
- top  消费排行返回的档案条数，1-{MAX_TOP}，默认 5。数值越大响应越大，
       只需合计数字时给 1 即可。

【返回值】
- totalPets / totalRecords / totalCharges   档案数 / 病历数 / 收费笔数
- totalRevenue      总收入（元）
- averageCost       客单价 = 总收入 / 档案数（元）
- maxCost           单只最高花费（元）
- bySpecies         按种类计数，如 {{"犬": 446, "猫": 387, ...}}
- byStatus          按就诊状态计数
- byDoctor          按医生计数
- revenueByDoctor   按医生聚合的收入（元）
- topSpenders       消费排行前 top 名的完整档案数组（含 records / charges）
- logGarbagePct     底层单文件数据库的日志垃圾占比（%），运维参考，不是业务数据

【错误码】
- VALIDATION_ERROR    top 不是整数、小于 1 或大于 {MAX_TOP}
- BACKEND_TIMEOUT / BACKEND_UNAVAILABLE / BACKEND_API_ERROR / BACKEND_INVALID_RESPONSE / INTERNAL_ERROR
  见服务说明

注意：topSpenders 里的档案含主人电话、住址、芯片号等个人信息，请勿在无关场合转述。
"""


def register(server: Any, client: PetHospitalClient) -> None:
    """把 ``get_stats`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_stats(
        top: int = Field(default=5, ge=1, le=MAX_TOP, description=f"消费排行条数，1-{MAX_TOP}，默认 5。"),
    ) -> HospitalStats:
        """读取全医院经营统计。"""
        try:
            # 第二道保险：入参已在 ContractMiddleware 里严格校验过。
            params = GetStatsInput(top=top)
        except ValidationError as exc:
            failure(ErrorCode.VALIDATION_ERROR, "输入参数校验失败。", validation_details(exc))

        try:
            return await client.get_stats(params.top)
        except ToolFailure as exc:
            failure(exc.code, exc.message, exc.details)
        except Exception:  # pragma: no cover - 兜底，绝不把堆栈泄漏给客户端
            logger.exception("unexpected failure while calling get_stats")
            failure(ErrorCode.INTERNAL_ERROR, "适配器内部错误。")
