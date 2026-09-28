"""宠物医院 MCP 适配器。

把现有 Go 宠物医院 REST API 的能力，以 MCP（Model Context Protocol）暴露给 AI Agent。

* 协议版本：MCP ``2026-07-28``（无状态核心）
* 服务类：官方 Python SDK 2.x 的 :class:`mcp.server.MCPServer`
* 传输：无状态 Streamable HTTP
* 后端：独立的 Go REST 服务，只经 HTTP 调用，不修改它
* 工具：6 个，全部只读 —— ``list_pets`` / ``get_pet`` / ``list_pet_records`` /
  ``list_pet_charges`` / ``get_pet_summary`` / ``get_stats``
"""

from __future__ import annotations

from .config import Settings
from .errors import ErrorCode, ErrorEnvelope, ToolFailure
from .rest_client import PetHospitalClient
from .server import SERVER_NAME, SERVER_VERSION, build_server, sdk_version
from .upstream import (
    Charge,
    HospitalStats,
    ListPetsData,
    MedicalRecord,
    PetChargesData,
    PetRecord,
    PetRecordsData,
    PetSummaryData,
)

__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "Charge",
    "ErrorCode",
    "ErrorEnvelope",
    "HospitalStats",
    "ListPetsData",
    "MedicalRecord",
    "PetChargesData",
    "PetHospitalClient",
    "PetRecord",
    "PetRecordsData",
    "PetSummaryData",
    "Settings",
    "ToolFailure",
    "build_server",
    "sdk_version",
]

__version__ = SERVER_VERSION
