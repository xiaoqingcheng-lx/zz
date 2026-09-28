"""``get_pet`` 工具：按主键读取单只宠物的完整档案（``GET /api/v1/pets/{id}``）。

阶段二新增工具。参数、返回值与错误码全部对应 Go 侧真实行为，不新增适配器私有参数。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..errors import ErrorCode, ToolFailure, failure
from ..logging_config import get_logger
from ..rest_client import PetHospitalClient
from ..upstream import PetRecord
from ._shared import PetId, PetIdInput

__all__ = ["TOOL_NAME", "TOOL_DESCRIPTION", "INPUT_MODEL", "register"]

logger = get_logger("tools.get_pet")

TOOL_NAME = "get_pet"

INPUT_MODEL = PetIdInput

TOOL_DESCRIPTION = """\
按档案编号读取**单只**宠物的完整档案：基本信息 + 主人信息 + 主治医生 + 疾病 + 就诊状态 +
过敏史 + 历史病历（records）+ 消费明细（charges）+ 总花费 + 就诊次数。
只读查询，不修改任何数据。

【用途】
已知 PET-000001 这类编号时，一次拿到这只宠物的全部字段，不必先列表再逐条筛选。

【适用场景】
- 「PET-000207 这只兔子什么情况」
- 先用 list_pets 定位到某只，再展开看它的完整病历与收费明细
- 需要主人的电话 / 住址等联系方式

【不适用】按条件批量筛选（用 list_pets）；只看病历（用 list_pet_records）；
只看花费明细（用 list_pet_charges）；只看费用汇总（用 get_pet_summary）。

【参数】
- id  宠物档案编号（必填），形如 PET-000001。编号由系统生成，客户端不能自定义，
      可以从 list_pets 返回的 items[].id 拿到。

【返回值】
单只宠物的完整档案对象，字段：id / name / species / breed / gender / ageMonths / color /
chipNo / ownerName / ownerPhone / ownerAddr / doctor / disease / status / allergy / note /
records（历史病历数组，可能为 null）/ charges（消费明细数组，可能为 null）/
totalCost（在医院总花费，元）/ visitCount（就诊次数）/ createdAt / updatedAt

【错误码】
- VALIDATION_ERROR    id 缺失，或格式不是 "PET-" + 数字
- BACKEND_API_ERROR   编号格式合法但档案不存在（details.status = 404）；或上游返回其它失败
- BACKEND_TIMEOUT / BACKEND_UNAVAILABLE / BACKEND_INVALID_RESPONSE / INTERNAL_ERROR  见服务说明

注意：返回值含主人电话与住址等个人信息，请勿在无关场合转述。
"""


def register(server: Any, client: PetHospitalClient) -> None:
    """把 ``get_pet`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_pet(id: PetId = Field(description="宠物档案编号，形如 PET-000001。")) -> PetRecord:
        """按档案编号读取单只宠物的完整档案。"""
        try:
            return await client.get_pet(id)
        except ToolFailure as exc:
            # 上游/解析类失败：已经带好统一错误码。
            failure(exc.code, exc.message, exc.details)
        except Exception:  # pragma: no cover - 兜底，绝不把堆栈泄漏给客户端
            logger.exception("unexpected failure while calling get_pet")
            failure(ErrorCode.INTERNAL_ERROR, "适配器内部错误。")
