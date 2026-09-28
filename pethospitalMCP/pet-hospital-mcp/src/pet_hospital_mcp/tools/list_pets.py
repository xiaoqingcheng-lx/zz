"""``list_pets`` 工具：把 ``GET /api/v1/pets`` 暴露给 AI Agent。

本模块是**唯一**新增工具的地方。后续阶段加工具时，只需在本目录再加一个模块并实现
``register(server, client)`` + ``INPUT_MODEL``，不需要改动 REST 客户端、日志或错误约定。

参数与 Go 后端一一对应，**不新增任何适配器私有业务参数**：::

    q name ownerName ownerPhone species doctor disease status
    min max sortBy order page pageSize

关于「严格校验」的实现位置
--------------------------
SDK 2.x 由函数签名生成的参数模型是宽松的（既不做类型强转拒绝，也允许未知字段）。
因此本模块额外声明了一份严格输入模型 :class:`ListPetsInput`，
由 :class:`pet_hospital_mcp.middleware.ContractMiddleware` 在**进入 SDK 处理前**
对原始 ``arguments`` 做一次校验，从而保证：

* 未知字段被拒绝（``extra="forbid"``）；
* ``"2"`` / ``1.5`` / ``true`` 这类类型不对的输入被拒绝（``strict=True``）；
* ``NaN`` / ``Infinity`` 被拒绝（``allow_inf_nan=False``）；
* 枚举、区间、``min <= max`` 越界被拒绝。

工具在函数体内会再构造一次同一个模型，作为第二道保险。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import ErrorCode, ToolFailure, failure, validation_details
from ..logging_config import get_logger
from ..rest_client import PetHospitalClient

# Charge / MedicalRecord / PetRecord / ListPetsData 被多个工具复用，定义在
# pet_hospital_mcp.upstream；这里再导出一次，保持
# `from ...tools.list_pets import ListPetsData` 这类既有引用继续可用。
from ..upstream import Charge, ListPetsData, MedicalRecord, PetRecord

__all__ = [
    "TOOL_NAME",
    "TOOL_DESCRIPTION",
    "INPUT_MODEL",
    "QUERY_PARAMS",
    "ListPetsInput",
    "ListPetsData",
    "PetRecord",
    "MedicalRecord",
    "Charge",
    "register",
]

logger = get_logger("tools.list_pets")

TOOL_NAME = "list_pets"

# ---------------------------------------------------------------------------
# 真实后端允许值（来自 Go 侧 internal/model/model.go 与 internal/api/api.go）
# ---------------------------------------------------------------------------

SpeciesValue = Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
StatusValue = Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
SortByValue = Literal[
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
]
OrderValue = Literal["asc", "desc"]

#: 后端 ``GET /api/v1/pets`` 支持的且**仅**支持的查询参数，顺序固定，便于断言与转发。
QUERY_PARAMS: tuple[str, ...] = (
    "q",
    "name",
    "ownerName",
    "ownerPhone",
    "species",
    "doctor",
    "disease",
    "status",
    "min",
    "max",
    "sortBy",
    "order",
    "page",
    "pageSize",
)

# ---------------------------------------------------------------------------
# 输入模型
# ---------------------------------------------------------------------------


class ListPetsInput(BaseModel):
    """``list_pets`` 的严格输入模型（字段与后端查询参数逐一对应）。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    q: str | None = Field(default=None, description="跨字段全文关键词，空格分词为 AND。")
    name: str | None = Field(default=None, description="宠物姓名模糊匹配。")
    ownerName: str | None = Field(default=None, description="主人姓名模糊匹配。")
    ownerPhone: str | None = Field(default=None, description="主人电话模糊匹配。")
    species: SpeciesValue | None = Field(default=None, description="宠物种类精确匹配。")
    doctor: str | None = Field(default=None, description="主治医生模糊匹配。")
    disease: str | None = Field(default=None, description="疾病 / 诊断模糊匹配。")
    status: StatusValue | None = Field(default=None, description="就诊状态精确匹配。")
    min: float | None = Field(default=None, ge=0, allow_inf_nan=False, description="总花费下限（元，含边界）。")
    max: float | None = Field(default=None, ge=0, allow_inf_nan=False, description="总花费上限（元，含边界）。")
    sortBy: SortByValue | None = Field(default=None, description="排序字段。")
    order: OrderValue | None = Field(default=None, description="排序方向。")
    page: int = Field(default=1, ge=1, description="页码，从 1 开始。")
    pageSize: int = Field(default=20, ge=1, le=500, description="每页条数，1-500。")

    @model_validator(mode="after")
    def _check_cost_range(self) -> ListPetsInput:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min 不能大于 max")
        return self

    def as_query(self) -> dict[str, Any]:
        """渲染成上游查询参数：只带非空过滤条件，``page``/``pageSize`` 始终带上。"""
        raw = self.model_dump(exclude_none=True)
        raw["page"] = self.page
        raw["pageSize"] = self.pageSize
        return {key: raw[key] for key in QUERY_PARAMS if key in raw}


#: 供 :mod:`pet_hospital_mcp.tools` 自动发现，契约中间件据此做严格校验。
INPUT_MODEL: type[BaseModel] = ListPetsInput


# ---------------------------------------------------------------------------
# 成功输出模型：见 _shared.py（模型见文件顶部导入）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 工具描述
# ---------------------------------------------------------------------------

TOOL_DESCRIPTION = """\
查询宠物医院的宠物档案列表：宠物 / 主人 / 电话 / 疾病 / 主治医生 / 就诊状态 / 历史病历 / 消费明细 / 总花费。
只读查询，不修改任何数据。

【用途】
把「按条件翻档案」这件事交给模型：过滤 + 排序 + 分页一次完成。

【适用场景】
- 按种类或状态盘点：「现在有哪些住院中的病例」「列出所有犬」
- 按人找宠物：「张三名下有哪些宠物」「这个电话对应的档案」
- 按疾病检索：「骨折的病例」「肠胃炎的宠物」
- 按花费筛选与排行：「总花费 1000 元以上的」「按总花费从高到低取前 5 条」
- 关键词全文检索：「病历里提到阿莫西林的」
- 带分页的批量浏览：「第 3 页，每页 50 条」

【不适用】按主键查单只宠物、新增/修改/删除档案、经营统计报表 —— 本服务当前只暴露列表查询。

【参数】全部可选；未提供的参数不参与过滤。
- q            跨字段全文关键词（宠物名 / 主人 / 电话 / 疾病 / 医生 / 病历全文；空格分词为 AND）
- name         宠物姓名模糊匹配
- ownerName    主人姓名模糊匹配
- ownerPhone   主人电话模糊匹配
- species      宠物种类精确匹配，取值：犬 / 猫 / 兔 / 鸟 / 仓鼠 / 爬宠 / 其他
- doctor       主治医生模糊匹配
- disease      疾病或诊断模糊匹配
- status       就诊状态精确匹配，取值：待就诊 / 就诊中 / 住院中 / 已康复 / 慢性病随访
- min          总花费下限（元，含边界，非负）
- max          总花费上限（元，含边界，非负；与 min 同时给出时必须 min <= max）
- sortBy       排序字段，取值：id / name / ownerName / species / doctor / disease / status
               / totalCost / visitCount / createdAt / updatedAt
- order        排序方向，取值：asc（升序）/ desc（降序）
- page         页码，从 1 开始，默认 1
- pageSize     每页条数，1-500，默认 20

【返回值】
结构化结果，字段与上游成功响应的 data 完全一致：
- items      当前页档案数组。每项含 id / name / species / breed / gender / ageMonths / color /
             chipNo / ownerName / ownerPhone / ownerAddr / doctor / disease / status / allergy /
             note / records（历史病历数组，可能为 null）/ charges（消费明细数组，可能为 null）/
             totalCost / visitCount / createdAt / updatedAt
- total      过滤后的档案总数
- page       当前页码
- pageSize   每页条数
- totalPages 总页数
- totalCost  当前过滤结果集的总花费合计（元）

失败时返回统一错误结构 {"error": {"code", "message", "details"}}，
code 取值：VALIDATION_ERROR / BACKEND_TIMEOUT / BACKEND_UNAVAILABLE /
BACKEND_API_ERROR / BACKEND_INVALID_RESPONSE / INTERNAL_ERROR。

【错误码】
- VALIDATION_ERROR             入参不合法：未知字段、类型不对（如 page 传 "2"）、
                               NaN / Infinity、枚举越界、page < 1、pageSize 超出 1-500、
                               min / max 为负、min > max。details.fields 会指出是哪个字段。
- BACKEND_TIMEOUT              调用上游超时，可稍后重试
- BACKEND_UNAVAILABLE          上游不可达，通常是 Go 服务没启动
- BACKEND_API_ERROR            上游应答了但业务失败（HTTP 4xx/5xx，或信封 code != 200）
- BACKEND_INVALID_RESPONSE     上游响应不是合法 JSON，或不符合约定模型
- INTERNAL_ERROR               适配器内部未预期错误（兜底）
"""


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------


def register(server: Any, client: PetHospitalClient) -> None:
    """把 ``list_pets`` 注册到 MCPServer 上。"""

    @server.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def list_pets(  # noqa: PLR0913 - 参数逐个对应后端查询参数，刻意保持扁平
        q: str | None = Field(default=None, description="跨字段全文关键词，空格分词为 AND。"),
        name: str | None = Field(default=None, description="宠物姓名模糊匹配。"),
        ownerName: str | None = Field(default=None, description="主人姓名模糊匹配。"),
        ownerPhone: str | None = Field(default=None, description="主人电话模糊匹配。"),
        species: SpeciesValue | None = Field(default=None, description="宠物种类精确匹配。"),
        doctor: str | None = Field(default=None, description="主治医生模糊匹配。"),
        disease: str | None = Field(default=None, description="疾病或诊断模糊匹配。"),
        status: StatusValue | None = Field(default=None, description="就诊状态精确匹配。"),
        min: float | None = Field(default=None, ge=0, allow_inf_nan=False, description="总花费下限（元）。"),
        max: float | None = Field(default=None, ge=0, allow_inf_nan=False, description="总花费上限（元）。"),
        sortBy: SortByValue | None = Field(default=None, description="排序字段。"),
        order: OrderValue | None = Field(default=None, description="排序方向：asc 升序 / desc 降序。"),
        page: int = Field(default=1, ge=1, description="页码，从 1 开始。"),
        pageSize: int = Field(default=20, ge=1, le=500, description="每页条数，1-500。"),
    ) -> ListPetsData:
        """查询宠物医院档案列表（过滤 + 排序 + 分页）。"""
        # 第二道保险：入参已在 ContractMiddleware 里严格校验过，这里再建一次模型，
        # 既拿到干净的查询参数，也保证直接调用该函数时同样安全。
        try:
            params = ListPetsInput(
                q=q,
                name=name,
                ownerName=ownerName,
                ownerPhone=ownerPhone,
                species=species,
                doctor=doctor,
                disease=disease,
                status=status,
                min=min,
                max=max,
                sortBy=sortBy,
                order=order,
                page=page,
                pageSize=pageSize,
            )
        except ValidationError as exc:
            failure(ErrorCode.VALIDATION_ERROR, "输入参数校验失败。", validation_details(exc))

        try:
            return await client.list_pets(params.as_query())
        except ToolFailure as exc:
            # 上游/解析类失败：已经带好统一错误码。
            failure(exc.code, exc.message, exc.details)
        except Exception:  # pragma: no cover - 兜底，绝不把堆栈泄漏给客户端
            logger.exception("unexpected failure while calling list_pets")
            failure(ErrorCode.INTERNAL_ERROR, "适配器内部错误。")
