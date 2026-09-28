"""上游 Go 宠物医院服务的响应模型。

放在包根而不是 ``tools/`` 下，是为了保持单向依赖：

.. code-block:: text

    upstream.py            （纯模型，只依赖 pydantic）
        ▲
    rest_client.py         （唯一解析上游响应的地方）
        ▲
    tools/*.py             （消费已解析的强类型结果）

如果这些模型放在 ``tools/`` 里，``rest_client`` 导入它们时就会触发 ``tools/__init__.py``，
而后者又要导入 ``rest_client``，形成循环导入。

关于 ``strict=True`` + ``extra="allow"``
---------------------------------------
上游是**别人写的** Go 服务，字段可能随版本增减。出参模型的目的不是「卡住上游」，
而是拿到结构保证，同时不因为上游多返回一个字段就整体失败，所以出参一律 ``extra="allow"``。

``strict=True`` 用来拒绝 ``"123"`` 这种用字符串伪装的数字。注意 Pydantic 严格模式下
``int`` → ``float`` 属于**无损**转换，仍然被接受 —— 这正是我们需要的：Go 把 ``0.0``
序列化成 ``0``（空结果集的 ``totalCost`` 就是这种情况），不能因此判成响应非法。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Charge",
    "HospitalStats",
    "ListPetsData",
    "MedicalRecord",
    "PetChargesData",
    "PetRecord",
    "PetRecordsData",
    "PetSummaryData",
    "UPSTREAM_CONFIG",
]

#: 上游出参模型的统一配置。
UPSTREAM_CONFIG = ConfigDict(extra="allow", strict=True)


class Charge(BaseModel):
    """一笔消费明细（对应 Go ``model.Treatment``）。"""

    model_config = UPSTREAM_CONFIG

    id: str | None = None
    item: str | None = None
    category: str | None = None
    amount: float | None = None
    doctor: str | None = None
    date: str | None = None
    note: str | None = None


class MedicalRecord(BaseModel):
    """一条历史病历（对应 Go ``model.MedicalRecord``）。"""

    model_config = UPSTREAM_CONFIG

    id: str | None = None
    visitDate: str | None = None
    doctor: str | None = None
    diagnosis: str | None = None
    symptoms: str | None = None
    treatment: str | None = None
    prescription: list[str] | None = None
    weightKg: float | None = None
    temperature: float | None = None
    followUp: str | None = None
    charge: float | None = None
    createdAt: str | None = None


class PetRecord(BaseModel):
    """一条宠物档案（对应 Go ``model.Pet``）。

    ``records`` / ``charges`` 在 Go 侧是 ``[]T``（无 ``omitempty``），未赋值时序列化为
    ``null``；有值时是数组。这里统一声明成 ``list[...] | None`` 以同时兼容两种表现。
    """

    model_config = UPSTREAM_CONFIG

    id: str
    name: str | None = None
    species: str | None = None
    breed: str | None = None
    gender: str | None = None
    ageMonths: int | None = None
    color: str | None = None
    chipNo: str | None = None

    ownerName: str | None = None
    ownerPhone: str | None = None
    ownerAddr: str | None = None

    doctor: str | None = None
    disease: str | None = None
    status: str | None = None
    allergy: str | None = None
    note: str | None = None

    records: list[MedicalRecord] | None = None
    charges: list[Charge] | None = None

    totalCost: float | None = None
    visitCount: int | None = None

    createdAt: str | None = None
    updatedAt: str | None = None


class ListPetsData(BaseModel):
    """``GET /api/v1/pets`` 成功响应中 ``data`` 的强类型表示。"""

    model_config = UPSTREAM_CONFIG

    items: list[PetRecord] = Field(description="当前页的宠物档案数组。")
    total: int = Field(description="过滤后的档案总数。")
    page: int = Field(description="当前页码。")
    pageSize: int = Field(description="每页条数。")
    totalPages: int = Field(description="总页数。")
    totalCost: float = Field(description="当前过滤结果集的总花费合计（元）。")


class PetRecordsData(BaseModel):
    """``GET /api/v1/pets/{id}/records`` 的 ``data``。"""

    model_config = UPSTREAM_CONFIG

    petId: str = Field(description="宠物档案编号。")
    petName: str | None = Field(default=None, description="宠物姓名。")
    ownerName: str | None = Field(default=None, description="主人姓名。")
    count: int = Field(default=0, description="病历条数。")
    records: list[MedicalRecord] | None = Field(
        default=None, description="历史病历数组；Go 侧保证空时是 [] 而不是 null。"
    )
    historyText: str | None = Field(default=None, description="病历的纯文本摘录，便于直接喂给模型。")


class PetChargesData(BaseModel):
    """``GET /api/v1/pets/{id}/charges`` 的 ``data``。"""

    model_config = UPSTREAM_CONFIG

    petId: str = Field(description="宠物档案编号。")
    petName: str | None = Field(default=None, description="宠物姓名。")
    count: int = Field(default=0, description="收费笔数。")
    charges: list[Charge] | None = Field(default=None, description="消费明细数组；Go 侧保证空时是 []。")
    totalCost: float = Field(default=0.0, description="该宠物总花费（元）。")
    costByCategory: dict[str, float] = Field(default_factory=dict, description="按收费分类聚合的金额（元）。")


class PetSummaryData(BaseModel):
    """``GET /api/v1/pets/{id}/summary`` 的 ``data``。"""

    model_config = UPSTREAM_CONFIG

    id: str = Field(description="宠物档案编号。")
    name: str | None = Field(default=None, description="宠物姓名。")
    species: str | None = Field(default=None, description="宠物种类。")
    ownerName: str | None = Field(default=None, description="主人姓名。")
    ownerPhone: str | None = Field(default=None, description="主人电话。")
    doctor: str | None = Field(default=None, description="主治医生。")
    disease: str | None = Field(default=None, description="疾病/主要诊断。")
    status: str | None = Field(default=None, description="就诊状态。")

    totalCost: float = Field(default=0.0, description="在医院总花费（元）。")
    visitCount: int = Field(default=0, description="就诊次数。")
    chargeCount: int = Field(default=0, description="收费笔数。")

    costByCategory: dict[str, float] = Field(default_factory=dict, description="按收费分类聚合的金额（元）。")
    costByDoctor: dict[str, float] = Field(default_factory=dict, description="按医生聚合的金额（元）。")

    maxSingleCharge: float = Field(default=0.0, description="单笔最高收费（元）。")
    avgCostPerVisit: float = Field(default=0.0, description="次均花费（元）。")

    firstVisit: str | None = Field(default=None, description="首次就诊日期。")
    lastVisit: str | None = Field(default=None, description="最近一次就诊日期。")
    historyText: str | None = Field(default=None, description="病历的纯文本摘录。")


class HospitalStats(BaseModel):
    """``GET /api/v1/stats`` 的 ``data``。"""

    model_config = UPSTREAM_CONFIG

    totalPets: int = Field(default=0, description="档案总数。")
    totalRecords: int = Field(default=0, description="病历总条数。")
    totalCharges: int = Field(default=0, description="收费总笔数。")
    totalRevenue: float = Field(default=0.0, description="总收入（元）。")
    averageCost: float = Field(default=0.0, description="客单价（元）。")
    maxCost: float = Field(default=0.0, description="单只最高花费（元）。")

    bySpecies: dict[str, int] = Field(default_factory=dict, description="按种类计数。")
    byStatus: dict[str, int] = Field(default_factory=dict, description="按就诊状态计数。")
    byDoctor: dict[str, int] = Field(default_factory=dict, description="按医生计数。")
    revenueByDoctor: dict[str, float] = Field(default_factory=dict, description="按医生聚合的收入（元）。")

    topSpenders: list[PetRecord] | None = Field(default=None, description="消费排行前列的完整档案。")
    logGarbagePct: float = Field(default=0.0, description="底层单文件数据库的日志垃圾占比（%），运维参考。")
