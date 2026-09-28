"""工具入参严格校验测试。

两部分：

1. :class:`pet_hospital_mcp.tools.list_pets.ListPetsInput` 本身的规则；
2. 这些规则在 MCP 边界上确实生效（通过 :class:`Client` 走真实派发链路，
   即会经过 :class:`pet_hospital_mcp.middleware.ContractMiddleware`），
   并且失败时返回的是统一错误信封，而不是 Pydantic 原文。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client
from pydantic import ValidationError

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.errors import ErrorCode
from pet_hospital_mcp.server import build_server
from pet_hospital_mcp.tools.list_pets import ListPetsInput, QUERY_PARAMS
from tests.helpers import EXPECTED_TOOLS

VALID_INPUTS: list[dict[str, Any]] = [
    {},
    {"page": 1, "pageSize": 20},
    {
        "q": "肠胃炎",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "species": "犬",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "住院中",
        "min": 0,
        "max": 10_000,
        "sortBy": "totalCost",
        "order": "desc",
        "page": 1,
        "pageSize": 500,
    },
    {"species": "爬宠", "status": "慢性病随访", "sortBy": "visitCount", "order": "asc"},
    {"min": 100, "max": 100},  # 允许相等
    {"min": 100},  # 只给下界
    {"max": 100},  # 只给上界
]

INVALID_INPUTS: list[tuple[str, dict[str, Any], str]] = [
    # 未知字段
    ("未知字段 qq", {"q": "a", "qq": "b"}, "qq"),
    ("未知字段 owner_name", {"owner_name": "张三"}, "owner_name"),
    ("未知字段 CamelCase 的同义私有参数", {"filter": {"species": "犬"}}, "filter"),
    # 枚举越界（真实后端不允许的值）
    ("species 不是后端允许值", {"species": "恐龙"}, "species"),
    ("species 英文", {"species": "dog"}, "species"),
    ("status 不是后端允许值", {"status": "已出院"}, "status"),
    ("sortBy 不是后端允许值", {"sortBy": "phone"}, "sortBy"),
    ("order 不是 asc/desc", {"order": "descending"}, "order"),
    ("order 大写", {"order": "DESC"}, "order"),
    # 分页边界
    ("page = 0", {"page": 0}, "page"),
    ("page 负数", {"page": -1}, "page"),
    ("pageSize = 0", {"pageSize": 0}, "pageSize"),
    ("pageSize 超过 500", {"pageSize": 501}, "pageSize"),
    # 花费区间
    ("min 负数", {"min": -1}, "min"),
    ("max 负数", {"max": -0.5}, "max"),
    ("min > max", {"min": 500, "max": 100}, "(body)"),
    # 类型不正确（strict：不做隐式强转）
    ("page 是字符串数字", {"page": "2"}, "page"),
    ("page 是小数", {"page": 1.5}, "page"),
    ("page 是布尔", {"page": True}, "page"),
    ("pageSize 是字符串", {"pageSize": "20"}, "pageSize"),
    ("min 是字符串数字", {"min": "100"}, "min"),
    ("q 是数字", {"q": 123}, "q"),
    ("species 是数字", {"species": 1}, "species"),
    ("arguments 传成对象嵌套", {"filters": {"species": "犬"}}, "filters"),
]


# ---------------------------------------------------------------------------
# 1. 模型本身
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", VALID_INPUTS)
def test_valid_inputs_accepted(payload: dict[str, Any]) -> None:
    model = ListPetsInput.model_validate(payload)
    assert 1 <= model.page
    assert 1 <= model.pageSize <= 500


def test_defaults() -> None:
    model = ListPetsInput.model_validate({})
    assert model.page == 1
    assert model.pageSize == 20
    assert model.as_query() == {"page": 1, "pageSize": 20}


def test_as_query_drops_none_and_opens_with_filters() -> None:
    model = ListPetsInput.model_validate({"species": "犬", "min": 100, "page": 2, "pageSize": 50})
    assert model.as_query() == {"species": "犬", "min": 100.0, "page": 2, "pageSize": 50}
    assert list(model.as_query()) == ["species", "min", "page", "pageSize"]


@pytest.mark.parametrize("label, payload, field", INVALID_INPUTS)
def test_invalid_inputs_rejected_by_model(label: str, payload: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        ListPetsInput.model_validate(payload)
    assert excinfo.value.errors(), label


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        ListPetsInput.model_validate({"min": bad})
    with pytest.raises(ValidationError):
        ListPetsInput.model_validate({"max": bad})


# ---------------------------------------------------------------------------
# 2. MCP 边界
# ---------------------------------------------------------------------------


@pytest.fixture
def in_process(make_client) -> Any:
    """返回 (server, client) —— 用 SDK 的进程内 Client 走完整派发链路（含中间件）。"""
    client = make_client()
    server, tools = build_server(Settings(base_url="http://127.0.0.1:8080"), client)
    assert tools == EXPECTED_TOOLS
    return server, client


@pytest.mark.parametrize("label, payload, field", INVALID_INPUTS)
async def test_invalid_input_returns_unified_envelope(in_process, label, payload, field) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("list_pets", payload)

    assert result.is_error is True, label
    texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
    assert len(texts) == 1
    envelope = json.loads(texts[0])
    assert envelope["error"]["code"] == ErrorCode.VALIDATION_ERROR.value, label
    assert envelope["error"]["message"]
    assert isinstance(envelope["error"]["details"], dict)
    # 绝不泄漏 Pydantic / SDK 原文
    lowered = texts[0].lower()
    for forbidden in ("pydantic", "errors.pydantic.dev", "traceback", "validation error for", "site-packages"):
        assert forbidden not in lowered, forbidden


async def test_unknown_field_reported_with_field_name(in_process) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("list_pets", {"species": "犬", "bogus": 1})

    assert result.is_error is True
    details = json.loads(result.content[0].text)["error"]["details"]
    assert any("bogus" in entry["field"] for entry in details["fields"])


async def test_min_greater_than_max_reports_readable_reason(in_process) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("list_pets", {"min": 500, "max": 100})

    envelope = json.loads(result.content[0].text)
    assert envelope["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
    reasons = " ".join(entry["reason"] for entry in envelope["error"]["details"]["fields"])
    assert "min" in reasons and "max" in reasons


async def test_enum_reason_lists_allowed_values_without_duplication(in_process) -> None:
    """枚举越界时，reason 要带上全部允许值，且不能把同一段文案粘两遍。"""
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("list_pets", {"species": "恐龙"})

    assert result.is_error is True
    envelope = json.loads(result.content[0].text)
    fields = envelope["error"]["details"]["fields"]
    entry = next(item for item in fields if item["field"] == "species")
    reason = entry["reason"]

    for allowed in ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"):
        assert allowed in reason, allowed
    # 允许值只描述一次：不允许 "Input should be X: X" 这种重复
    assert reason.count("Input should be") == 1, reason
    head, sep, tail = reason.partition(": ")
    assert not (sep and tail and tail in head), reason


async def test_valid_input_reaches_the_backend(in_process, recorder) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("list_pets", {"species": "犬", "page": 2, "pageSize": 5})

    assert result.is_error is False
    assert recorder.calls == 1
    assert recorder.params_of() == {"species": "犬", "page": "2", "pageSize": "5"}
    assert result.structured_content["total"] == 1
