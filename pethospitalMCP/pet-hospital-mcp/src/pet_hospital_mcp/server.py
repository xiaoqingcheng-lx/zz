"""MCP 服务装配。

技术选型（对应 MCP 2026-07-28 与官方 Python SDK 2.x）
-----------------------------------------------------
* 服务类：``mcp.server.MCPServer``（SDK 2.x 把 1.x 的 ``FastMCP`` 改名为 ``MCPServer``，
  旧导入路径 ``mcp.server.fastmcp`` 已不存在，本项目不使用也不再兼容）。
* 传输：**无状态 Streamable HTTP** —— ``streamable_http_app(stateless_http=True,
  json_response=True)``。每个请求自带协议版本与客户端信息，服务端不建会话、
  不返回 ``Mcp-Session-Id``、不做会话恢复。
* 发现：2026-07-28 用可选的 ``server/discover`` RPC 取代了 ``initialize`` 握手，
  由 SDK 内置处理，本项目无需自己实现。
* 传输配置（host / port / stateless_http / 端点路径）在 SDK 2.x 里属于 ``run()`` /
  ``streamable_http_app()``，**不能**传给 ``MCPServer(...)`` 构造器。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Any

from mcp.server import MCPServer
from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import Settings
from .logging_config import get_logger
from .middleware import ContractMiddleware
from .rest_client import PetHospitalClient
from .tools import input_models, register_tools

__all__ = ["SERVER_NAME", "SERVER_INSTRUCTIONS", "SERVER_VERSION", "build_server", "sdk_version"]

logger = get_logger("server")

SERVER_NAME = "pet-hospital-mcp"

SERVER_INSTRUCTIONS = """\
本服务把本地宠物医院（Go REST API）的**只读**查询能力暴露给 AI Agent。
全部工具都不修改数据，也不存在新增/修改/删除类工具。

工具清单与选择建议：
- `list_pets`         按关键词/字段/花费区间过滤 + 排序 + 分页，适合「有哪些宠物」「谁养的」
                      「什么病」「花了多少钱」这类**跨档案**的列表问题。返回 total / totalPages，
                      结果多时按需翻页。
- `get_pet`           已知档案编号（PET-000001 这种）时，一次拿到该宠物**完整字段**
                      （含 historyText 之外的 records / charges 原样数组）。
- `list_pet_records`  只看某只宠物的**历史病历**（就诊时间、诊断、治疗、处方、随访）。
- `list_pet_charges`  只看某只宠物的**消费明细**与分类小计。
- `get_pet_summary`   只看某只宠物的**费用与就诊汇总**（总花费、次均花费、按分类/按医生的分布、
                      首末就诊日期、病程文本），比同时调 records + charges 更省 token。
- `get_stats`         全医院口径的经营统计（档案数、总收入、客单价、按种类/状态/医生分布、
                      消费排行），**不做过滤**。

使用建议：
1. 先用 `list_pets` 找到目标档案的 id，再用按 id 的工具下钻；
2. 用 `list_pets` 的 `q` 做跨字段全文检索（含病历全文），`species` / `status` / `doctor` /
   `disease` 做精确或模糊过滤；
3. 排序用 `sortBy` + `order`（例如 `sortBy="totalCost"`, `order="desc"`）；
4. 工具返回的档案含主人电话、住址、芯片号等个人信息，只在与用户当前问题相关时转述；
5. 入参不合法或上游异常时，工具返回统一错误结构 {"error": {"code", "message", "details"}}，
   `error.code` 可用于判断该改写参数（VALIDATION_ERROR）还是稍后重试（BACKEND_TIMEOUT 等）。
   按编号查询时，编号合法但档案不存在会返回 BACKEND_API_ERROR（`details.status = 404`）。
"""


def sdk_version() -> str:
    """已安装的官方 MCP Python SDK 版本。"""
    try:
        return _pkg_version("mcp")
    except PackageNotFoundError:  # pragma: no cover - 源码直跑且未安装元数据
        return "unknown"


def _package_version() -> str:
    try:
        return _pkg_version("pet-hospital-mcp")
    except PackageNotFoundError:  # pragma: no cover - 源码直跑（未 pip install）
        return "0.1.0"


#: 本适配器版本，用于 server/discover 的 serverInfo 与 /health。
SERVER_VERSION = _package_version()


def build_server(settings: Settings, client: PetHospitalClient) -> tuple[MCPServer, list[str]]:
    """装配 ``MCPServer``：注册契约中间件、注册工具、挂 ``/health``。

    返回 ``(server, 已注册工具名列表)``。
    """
    models = input_models()
    server = MCPServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=SERVER_INSTRUCTIONS,
        # 严格入参校验 + 统一错误结构 + 工具调用日志。
        middleware=[ContractMiddleware(models, server_name=SERVER_NAME, server_version=SERVER_VERSION)],
        log_level=settings.log_level,
    )

    registered = register_tools(server, client)

    @server.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        """健康检查。

        默认只报告本进程状态（始终 200）；带 ``?probe=upstream`` 时额外探测上游 Go 服务，
        但**不会**因为上游不可用而返回非 200 —— MCP 服务本身仍然是健康的。
        """
        payload: dict[str, Any] = {
            "status": "ok",
            "service": SERVER_NAME,
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "sdkVersion": sdk_version(),
            "mcpEndpoint": settings.mcp_path,
            "upstreamBaseUrl": settings.base_url,
            "tools": registered,
        }
        if (request.query_params.get("probe") or "").lower() in {"upstream", "1", "true"}:
            payload["upstream"] = await _probe_upstream(client)
        return JSONResponse(payload)

    return server, registered


async def _probe_upstream(client: PetHospitalClient) -> dict[str, Any]:
    """轻量探测上游是否可用（不抛异常，只报告）。"""
    try:
        await client.list_pets({"page": 1, "pageSize": 1})
    except Exception as exc:  # noqa: BLE001 - 只做诊断，任何失败都如实报告
        return {"status": "down", "reason": type(exc).__name__, "message": str(exc)[:200]}
    return {"status": "up"}
