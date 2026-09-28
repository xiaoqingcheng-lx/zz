"""``list_pet_records`` 工具：单只宠物的历史病历（``GET /api/v1/pets/{id}/records``）。

阶段二新增工具。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..errors import ErrorCode, ToolFailure, failure
from ..logging_config import get_logger
from ..rest_client import PetHospitalClient
from ..upstream import PetRecordsData
from ._shared import PetId, PetIdInput

__all__ = ["TOOL_NAME", "TOOL_DESCRIPTION", "INPUT_MODEL", "register"]

logger = get_logger("tools.list_pet_records")

TOOL_NAME = "list_pet_records"

INPUT_MODEL = PetIdInput

TOOL_DESCRIPTION = """\
读取**某一只**宠物的历史病历列表（就诊记录）。只读查询，不修改任何数据。

【用途】
把「这只宠物看过几次病、每次诊断是什么、怎么治的、开了什么药」交给模型，
用于梳理病程、复诊建议、用药历史。

【适用场景】
- 「PET-000207 的就诊记录」
- 「这只猫之前用过哪些药」
- 「这个病例的病程发展」——按 visitDate 顺序看 diagnosis / treatment / prescription
- 想拿纯文本病程时直接用返回的 historyText，不必自己拼字段

【不适用】跨宠物的病历检索（用 list_pets 的 q 参数，它包含病历全文）；
单只宠物的消费金额（用 list_pet_charges）；费用汇总（用 get_pet_summary）。

【参数】
- id  宠物档案编号（必填），形如 PET-000001。

【返回值】
- petId        宠物档案编号
- petName      宠物姓名
- ownerName    主人姓名
- count        病历条数
- records      历史病历数组（无病历时为 []，不会是 null）。每条含
               id / visitDate / doctor / diagnosis / symptoms / treatment /
               prescription（处方药数组）/ weightKg / temperature / followUp /
               charge（该次收费，元）/ createdAt
- historyText  病历的纯文本摘录，形如 "2024-05-24 王医生 球虫病 清洁笼具 处方:妥曲珠利"

【错误码】
- VALIDATION_ERROR    id 缺失，或格式不是 "PET-" + 数字
- BACKEND_API_ERROR   编号格式合法但档案不存在（details.status = 404）；或上游返回其它失败
- BACKEND_TIMEOUT / BACKEND_UNAVAILABLE / BACKEND_INVALID_RESPONSE / INTERNAL_ERROR  见服务说明
"""


def register(server: Any, client: PetHospitalClient) -> None:
    """把 ``list_pet_records`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def list_pet_records(id: PetId = Field(description="宠物档案编号，形如 PET-000001。")) -> PetRecordsData:
        """读取单只宠物的历史病历列表。"""
        try:
            return await client.list_pet_records(id)
        except ToolFailure as exc:
            failure(exc.code, exc.message, exc.details)
        except Exception:  # pragma: no cover - 兜底，绝不把堆栈泄漏给客户端
            logger.exception("unexpected failure while calling list_pet_records")
            failure(ErrorCode.INTERNAL_ERROR, "适配器内部错误。")
