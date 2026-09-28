"""MCP 工具注册、命名与 JSON Schema 测试。

覆盖阶段一（``list_pets``）与阶段二（5 个只读工具）的对外契约。
"""

from __future__ import annotations

from typing import Any

import pytest

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.server import SERVER_NAME, build_server
from pet_hospital_mcp.tools import input_models
from pet_hospital_mcp.tools.get_stats import MAX_TOP
from pet_hospital_mcp.tools.list_pets import QUERY_PARAMS, TOOL_NAME
from tests.helpers import EXPECTED_TOOLS, ID_TOOLS

EXPECTED_DATA_KEYS = ["items", "total", "page", "pageSize", "totalPages", "totalCost"]

#: 工具描述必须自解释的六段式（section, 关键词）。
DESCRIPTION_SECTIONS = ("用途", "适用场景", "不适用", "参数", "返回值", "错误码")


async def tools_by_name(make_client) -> dict[str, Any]:
    server, _ = build_server(Settings(base_url="http://127.0.0.1:8080"), make_client())
    return {tool.name: tool for tool in await server.list_tools()}


# ---------------------------------------------------------------------------
# 工具集
# ---------------------------------------------------------------------------


async def test_registered_tools_are_exactly_the_expected_read_only_set(make_client) -> None:
    """工具集是确定的：1 个列表查询 + 5 个阶段二只读查询，不含任何写操作。"""
    server, tools = build_server(Settings(base_url="http://127.0.0.1:8080"), make_client())
    registered = [tool.name for tool in await server.list_tools()]

    assert registered == EXPECTED_TOOLS
    assert tools == EXPECTED_TOOLS


def test_every_registered_module_exposes_a_strict_input_model() -> None:
    """每个被注册的工具都必须挂上严格输入模型，否则中间件不会做校验。"""
    assert sorted(input_models()) == EXPECTED_TOOLS


@pytest.mark.parametrize("name", EXPECTED_TOOLS)
def test_tool_name_is_snake_case(name: str) -> None:
    assert name == name.lower()
    assert " " not in name and "-" not in name


# ---------------------------------------------------------------------------
# list_pets 的入参 / 出参 schema
# ---------------------------------------------------------------------------


async def test_list_pets_input_schema_has_exactly_the_backend_query_params(make_client) -> None:
    schema = (await tools_by_name(make_client))[TOOL_NAME].input_schema

    assert schema["type"] == "object"
    assert list(schema["properties"]) == list(QUERY_PARAMS)
    # 不新增适配器私有业务参数
    assert len(schema["properties"]) == 14
    assert not schema.get("required"), "所有参数都应可选，只有 page/pageSize 有默认值"


async def test_list_pets_input_schema_carries_enums_and_bounds(make_client) -> None:
    props = (await tools_by_name(make_client))[TOOL_NAME].input_schema["properties"]

    def flatten(node: dict) -> dict:
        """可空参数的约束落在 anyOf 分支里，这里合并回一层便于断言。"""
        merged: dict = {}
        for candidate in node.get("anyOf", [node]):
            merged.update(candidate)
        return merged

    assert flatten(props["species"])["enum"] == ["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
    assert flatten(props["status"])["enum"] == ["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
    assert flatten(props["sortBy"])["enum"] == [
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
    assert flatten(props["order"])["enum"] == ["asc", "desc"]

    assert props["page"]["minimum"] == 1
    assert props["page"]["default"] == 1
    assert props["pageSize"]["minimum"] == 1
    assert props["pageSize"]["maximum"] == 500
    assert props["pageSize"]["default"] == 20
    assert flatten(props["min"])["minimum"] == 0
    assert flatten(props["max"])["minimum"] == 0


async def test_list_pets_output_schema_matches_go_data_shape(make_client) -> None:
    tool = (await tools_by_name(make_client))[TOOL_NAME]

    assert tool.output_schema is not None
    assert list(tool.output_schema["properties"]) == EXPECTED_DATA_KEYS


# ---------------------------------------------------------------------------
# 阶段二工具的入参 / 出参 schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ID_TOOLS)
async def test_id_tools_require_a_pet_id(make_client, name: str) -> None:
    """四个按 id 查的工具入参形状完全一致：只有一个必填的 id。

    ``additionalProperties: false`` 由契约中间件在 ``tools/list`` 响应上补，
    不在这份 SDK 直出的 schema 里，见 ``test_http_tools_list_declares_closed_input_schema``。
    """
    schema = (await tools_by_name(make_client))[name].input_schema

    assert list(schema["properties"]) == ["id"]
    assert schema.get("required") == ["id"], "id 必须是必填项"
    assert schema["properties"]["id"]["type"] == "string"
    assert schema["properties"]["id"]["pattern"] == r"^PET-[0-9]{1,12}$"


async def test_get_stats_input_schema_bounds_top(make_client) -> None:
    props = (await tools_by_name(make_client))["get_stats"].input_schema["properties"]

    assert list(props) == ["top"]
    assert props["top"]["minimum"] == 1
    assert props["top"]["maximum"] == MAX_TOP
    assert props["top"]["default"] == 5


async def test_get_stats_output_schema_covers_the_go_stats_shape(make_client) -> None:
    tool = (await tools_by_name(make_client))["get_stats"]
    keys = list(tool.output_schema["properties"])

    for key in (
        "totalPets",
        "totalRecords",
        "totalCharges",
        "totalRevenue",
        "averageCost",
        "maxCost",
        "bySpecies",
        "byStatus",
        "byDoctor",
        "revenueByDoctor",
        "topSpenders",
    ):
        assert key in keys, key


# ---------------------------------------------------------------------------
# 工具描述质量
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", EXPECTED_TOOLS)
async def test_every_tool_description_is_self_explanatory(make_client, name: str) -> None:
    description = (await tools_by_name(make_client))[name].description or ""

    assert len(description) > 200, name
    for heading in DESCRIPTION_SECTIONS:
        assert heading in description, f"{name} 缺少「{heading}」"
    for code in ("VALIDATION_ERROR", "BACKEND_TIMEOUT", "BACKEND_UNAVAILABLE", "BACKEND_API_ERROR"):
        assert code in description, f"{name} 未说明 {code}"


async def test_list_pets_description_mentions_every_param_and_return_key(make_client) -> None:
    description = (await tools_by_name(make_client))[TOOL_NAME].description or ""

    for param in QUERY_PARAMS:
        assert param in description, param
    for key in EXPECTED_DATA_KEYS:
        assert key in description, key


# ---------------------------------------------------------------------------
# 服务身份
# ---------------------------------------------------------------------------


async def test_server_identity_and_instructions(make_client) -> None:
    server, _ = build_server(Settings(base_url="http://127.0.0.1:8080"), make_client())
    assert server.name == SERVER_NAME == "pet-hospital-mcp"
    assert server.instructions
    assert "list_pets" in server.instructions


async def test_server_instructions_no_longer_claim_a_single_tool(make_client) -> None:
    """阶段二之后，instructions 不能再说「只有 list_pets 一个工具」。"""
    server, _ = build_server(Settings(base_url="http://127.0.0.1:8080"), make_client())
    instructions = server.instructions or ""

    for name in EXPECTED_TOOLS:
        assert name in instructions, name


# ---------------------------------------------------------------------------
# 线上 schema（经过契约中间件补 additionalProperties: false）
# ---------------------------------------------------------------------------


def test_http_tools_list_declares_closed_input_schema(http_mcp) -> None:
    payload = http_mcp.list_tools().json()["result"]
    by_name = {tool["name"]: tool for tool in payload["tools"]}

    assert sorted(by_name) == EXPECTED_TOOLS
    for name, tool in by_name.items():
        assert tool["inputSchema"]["additionalProperties"] is False, name
        # 未知字段确实会被中间件拒绝，schema 与行为必须一致
        assert tool["inputSchema"]["type"] == "object"

    assert list(by_name[TOOL_NAME]["inputSchema"]["properties"]) == list(QUERY_PARAMS)
    assert list(by_name[TOOL_NAME]["outputSchema"]["properties"]) == EXPECTED_DATA_KEYS


def test_http_tools_list_is_cacheable_and_ordered(http_mcp) -> None:
    """2026-07-28 起 list 结果带缓存提示与确定性顺序。"""
    payload = http_mcp.list_tools().json()["result"]
    assert "ttlMs" in payload
    assert payload.get("cacheScope") in {"public", "private"}
    assert payload.get("resultType") == "complete"
