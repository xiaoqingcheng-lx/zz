"""阶段二 5 个只读工具的测试。

两个层次：

1. **REST 客户端层** —— 每个新方法打到正确的上游路径、参数转发正确、
   失败映射到正确的错误码；上游全部用 ``httpx.MockTransport`` 打桩，不碰真实 Go 服务。
2. **MCP 边界层** —— 严格入参校验、统一错误信封、不泄漏框架原文、
   以及「每个工具的校验路由到自己那份模型」。
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest
from mcp import Client

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.errors import ErrorCode, ToolFailure
from pet_hospital_mcp.server import build_server
from pet_hospital_mcp.tools import input_models
from pet_hospital_mcp.tools._shared import PetIdInput
from pet_hospital_mcp.tools.get_stats import GetStatsInput
from tests.helpers import (
    EXPECTED_TOOLS,
    ID_TOOLS,
    captured_json_logs,
    go_envelope,
    json_log_records,
    sample_charges_data,
    sample_data,
    sample_pet,
    sample_records_data,
    sample_stats,
    sample_summary_data,
)

PET_ID = "PET-000001"

#: (工具名, 上游路径后缀, 假数据构造器, 该响应里必填的字符串字段)
#: 最后一个字段用于「把必填字符串改成数字，验证模型校验确实生效」。
TOOL_CASES: list[tuple[str, str, Callable[[], dict[str, Any]], str]] = [
    ("get_pet", "", lambda: sample_pet(), "id"),
    ("list_pet_records", "/records", sample_records_data, "petId"),
    ("list_pet_charges", "/charges", sample_charges_data, "petId"),
    ("get_pet_summary", "/summary", sample_summary_data, "id"),
]

CASE_IDS = [case[0] for case in TOOL_CASES]

ID_TOOL_CASES = [case for case in TOOL_CASES if case[0] in ID_TOOLS]


def _text_of(result: Any) -> str:
    texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
    assert len(texts) == 1, texts
    return texts[0]


def _envelope_of(result: Any) -> dict[str, Any]:
    return json.loads(_text_of(result))


@pytest.fixture
def in_process(make_client) -> Any:
    client = make_client()
    server, tools = build_server(Settings(base_url="http://127.0.0.1:8080"), client)
    assert tools == EXPECTED_TOOLS
    return server, client


# ---------------------------------------------------------------------------
# 1. REST 客户端层：路径与参数转发
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", TOOL_CASES, ids=CASE_IDS)
async def test_id_methods_hit_the_right_upstream_path(
    make_client, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    recorder.queue_json(go_envelope(payload_factory()))
    client = make_client()

    await getattr(client, tool_name)(PET_ID)

    assert recorder.calls == 1
    assert recorder.last_url.path == f"/api/v1/pets/{PET_ID}{suffix}"
    assert recorder.params_of() == {}, "按 id 查的接口不带查询参数"
    await client.aclose()


async def test_get_stats_forwards_top(make_client, recorder) -> None:
    recorder.queue_json(go_envelope(sample_stats()))
    client = make_client()

    stats = await client.get_stats(7)

    assert recorder.last_url.path == "/api/v1/stats"
    assert recorder.params_of() == {"top": "7"}
    assert stats.totalPets == 2
    assert stats.topSpenders and stats.topSpenders[0].id == "PET-000001"
    await client.aclose()


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", TOOL_CASES, ids=CASE_IDS)
async def test_id_methods_accept_null_collections(
    make_client, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    """Go 侧 ``[]T`` 既可能是 ``null`` 也可能是数组，两种都要能解析。"""
    payload = dict(payload_factory())
    nullable = [key for key in ("records", "charges") if key in payload]
    for key in nullable:
        payload[key] = None

    recorder.queue_json(go_envelope(payload))
    client = make_client()

    result = await getattr(client, tool_name)(PET_ID)

    for key in nullable:
        assert getattr(result, key) is None, key
    await client.aclose()


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", TOOL_CASES, ids=CASE_IDS)
async def test_id_methods_surface_404_as_backend_api_error(
    make_client, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    """编号格式合法但不存在时，Go 返回 404 + 读得懂的中文消息。"""
    body = {"code": 404, "message": f"记录不存在: id={PET_ID}", "time": "2026-09-17T10:00:00+08:00"}
    recorder.queue_raw(json.dumps(body, ensure_ascii=False).encode(), status=404)
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await getattr(client, tool_name)(PET_ID)

    failure = excinfo.value
    assert failure.code is ErrorCode.BACKEND_API_ERROR
    assert failure.details["status"] == 404
    assert "记录不存在" in failure.message
    await client.aclose()


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", TOOL_CASES, ids=CASE_IDS)
async def test_id_methods_map_timeout(
    make_client, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    recorder.queue_exception(httpx.ReadTimeout("too slow"))
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await getattr(client, tool_name)(PET_ID)
    assert excinfo.value.code is ErrorCode.BACKEND_TIMEOUT
    await client.aclose()


@pytest.mark.parametrize("tool_name, suffix, payload_factory, key", TOOL_CASES, ids=CASE_IDS)
async def test_id_methods_map_bad_model(
    make_client, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], key: str
) -> None:
    """响应模型不匹配时报 BACKEND_INVALID_RESPONSE，并把出错的字段名带出来。"""
    payload = dict(payload_factory())
    payload[key] = 123  # 该字段是必填字符串
    recorder.queue_json(go_envelope(payload))
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await getattr(client, tool_name)(PET_ID)
    assert excinfo.value.code is ErrorCode.BACKEND_INVALID_RESPONSE
    assert key in excinfo.value.details["fields"]
    await client.aclose()


async def test_stats_maps_bad_model(make_client, recorder) -> None:
    recorder.queue_json(go_envelope({"totalPets": "many"}))
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.get_stats(5)
    assert excinfo.value.code is ErrorCode.BACKEND_INVALID_RESPONSE
    await client.aclose()


async def test_stats_maps_connection_error(make_client, recorder) -> None:
    recorder.queue_exception(httpx.ConnectError("connection refused"))
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.get_stats(5)
    assert excinfo.value.code is ErrorCode.BACKEND_UNAVAILABLE
    await client.aclose()


# ---------------------------------------------------------------------------
# 2. 工具边界：严格入参
# ---------------------------------------------------------------------------

INVALID_IDS: list[tuple[str, dict[str, Any]]] = [
    ("缺少 id", {}),
    ("id 为空串", {"id": ""}),
    ("id 全空白", {"id": "   "}),
    ("id 前缀不对", {"id": "DOG-000001"}),
    ("id 小写", {"id": "pet-000001"}),
    ("id 缺序号", {"id": "PET-"}),
    ("id 含非数字", {"id": "PET-ABC001"}),
    ("id 是数字类型", {"id": 1}),
    ("id 是 null", {"id": None}),
    ("多给未知字段", {"id": PET_ID, "name": "旺财"}),
    ("把 list_pets 的参数传进来", {"species": "犬"}),
]


@pytest.mark.parametrize("tool_name", ID_TOOLS)
@pytest.mark.parametrize("label, payload", INVALID_IDS, ids=[case[0] for case in INVALID_IDS])
async def test_id_tools_reject_invalid_input_with_unified_envelope(
    in_process, tool_name: str, label: str, payload: dict[str, Any]
) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool(tool_name, payload)

    assert result.is_error is True, f"{tool_name} / {label}"
    text = _text_of(result)
    envelope = json.loads(text)
    assert envelope["error"]["code"] == ErrorCode.VALIDATION_ERROR.value, f"{tool_name} / {label}"

    lowered = text.lower()
    for forbidden in ("pydantic", "errors.pydantic.dev", "traceback", "validation error for", "site-packages"):
        assert forbidden not in lowered, (tool_name, forbidden)


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", ID_TOOL_CASES, ids=[c[0] for c in ID_TOOL_CASES])
async def test_id_tools_forward_the_id_to_the_backend(
    in_process, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    server, _ = in_process
    recorder.queue_json(go_envelope(payload_factory()))

    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool(tool_name, {"id": PET_ID})

    assert result.is_error is False
    assert recorder.last_url.path == f"/api/v1/pets/{PET_ID}{suffix}"


async def test_id_is_trimmed_before_hitting_the_backend(in_process, recorder) -> None:
    server, _ = in_process
    recorder.queue_json(go_envelope(sample_pet()))

    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("get_pet", {"id": f"  {PET_ID}  "})

    assert result.is_error is False
    assert recorder.last_url.path == f"/api/v1/pets/{PET_ID}"


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", ID_TOOL_CASES, ids=[c[0] for c in ID_TOOL_CASES])
async def test_upstream_404_becomes_backend_api_error_at_mcp_boundary(
    in_process, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    """编号不存在时，模型看到的错误里要能一眼看出是 404。"""
    server, _ = in_process
    recorder.queue_raw(
        json.dumps({"code": 404, "message": "记录不存在: id=PET-999999"}, ensure_ascii=False).encode(),
        status=404,
    )

    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool(tool_name, {"id": "PET-999999"})

    assert result.is_error is True
    envelope = _envelope_of(result)
    assert envelope["error"]["code"] == ErrorCode.BACKEND_API_ERROR.value
    assert envelope["error"]["details"]["status"] == 404


# ---------------------------------------------------------------------------
# 3. get_stats 的入参
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, 101, 1.5, "5", True, None], ids=repr)
async def test_get_stats_rejects_out_of_range_top(in_process, bad: Any) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("get_stats", {"top": bad})

    assert result.is_error is True, repr(bad)
    envelope = _envelope_of(result)
    assert envelope["error"]["code"] == ErrorCode.VALIDATION_ERROR.value


async def test_get_stats_rejects_unknown_field(in_process) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("get_stats", {"limit": 3})

    assert result.is_error is True
    envelope = _envelope_of(result)
    assert envelope["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
    assert any("limit" in entry["field"] for entry in envelope["error"]["details"]["fields"])


@pytest.mark.parametrize("top, expected", [(None, "5"), (1, "1"), (100, "100")])
async def test_get_stats_forwards_valid_top(in_process, recorder, top: Any, expected: str) -> None:
    server, _ = in_process
    recorder.queue_json(go_envelope(sample_stats()))
    arguments = {} if top is None else {"top": top}

    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("get_stats", arguments)

    assert result.is_error is False
    assert recorder.params_of() == {"top": expected}


async def test_get_stats_returns_structured_content(in_process, recorder) -> None:
    server, _ = in_process
    recorder.queue_json(go_envelope(sample_stats()))

    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("get_stats", {"top": 2})

    assert result.is_error is False
    content = result.structured_content
    assert content["totalPets"] == 2
    assert content["bySpecies"] == {"犬": 1, "猫": 1}
    assert content["topSpenders"][0]["id"] == "PET-000001"


# ---------------------------------------------------------------------------
# 4. 校验按工具名路由：每个工具只认自己那份模型
# ---------------------------------------------------------------------------


def test_each_tool_is_bound_to_its_own_input_model() -> None:
    models = input_models()

    for name in ID_TOOLS:
        assert models[name] is PetIdInput, name
    assert models["get_stats"] is GetStatsInput


async def test_get_pet_does_not_accept_list_pets_params(in_process) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool("get_pet", {"species": "犬", "pageSize": 5})

    assert result.is_error is True
    envelope = _envelope_of(result)
    fields = {entry["field"] for entry in envelope["error"]["details"]["fields"]}
    assert "id" in fields, "缺 id 也要被指出"
    assert "species" in fields or "pageSize" in fields, "未知字段也要被指出"


@pytest.mark.parametrize("tool_name, payload", [
    ("list_pets", {"id": PET_ID}),
    ("get_stats", {"id": PET_ID}),
    ("list_pet_records", {"species": "犬"}),
])
async def test_tools_reject_other_tools_params(in_process, tool_name: str, payload: dict[str, Any]) -> None:
    server, _ = in_process
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool(tool_name, payload)

    assert result.is_error is True
    envelope = _envelope_of(result)
    assert envelope["error"]["code"] == ErrorCode.VALIDATION_ERROR.value


# ---------------------------------------------------------------------------
# 5. 日志：工具名正确、字段齐全、不含敏感原文
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", ID_TOOL_CASES, ids=[c[0] for c in ID_TOOL_CASES])
async def test_new_tools_are_logged_with_their_own_name(
    in_process, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    recorder.queue_json(go_envelope(payload_factory()))
    server, _ = in_process

    with captured_json_logs() as stream:
        async with Client(server) as mcp_client:
            await mcp_client.call_tool(tool_name, {"id": PET_ID})

    calls = [record for record in json_log_records(stream) if record.get("tool_name") == tool_name]
    assert len(calls) == 1, tool_name
    assert calls[0]["params"] == {"id": PET_ID}
    assert calls[0]["status"] == "ok"
    assert set(calls[0]) >= {"timestamp", "tool_name", "params", "status", "duration_ms"}


async def test_get_pet_summary_log_never_leaks_the_owner_phone(in_process, recorder) -> None:
    """``summary`` 的响应里有 ownerPhone，但日志里只能出现入参 id。"""
    recorder.queue_json(go_envelope(sample_summary_data()))
    server, _ = in_process

    with captured_json_logs() as stream:
        async with Client(server) as mcp_client:
            await mcp_client.call_tool("get_pet_summary", {"id": PET_ID})

    text = stream.getvalue()
    assert "13800001111" not in text
    calls = [record for record in json_log_records(stream) if record.get("tool_name") == "get_pet_summary"]
    assert calls[0]["status"] == "ok"


async def test_failed_new_tool_call_is_logged_with_error_code(in_process) -> None:
    server, _ = in_process

    with captured_json_logs() as stream:
        async with Client(server) as mcp_client:
            await mcp_client.call_tool("get_stats", {"top": 999})

    calls = [record for record in json_log_records(stream) if record.get("tool_name") == "get_stats"]
    assert len(calls) == 1
    assert calls[0]["status"] == ErrorCode.VALIDATION_ERROR.value


# ---------------------------------------------------------------------------
# 6. HTTP 链路：新工具在无状态端点上同样可用
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name, suffix, payload_factory, _key", ID_TOOL_CASES, ids=[c[0] for c in ID_TOOL_CASES])
def test_new_tools_are_callable_over_stateless_http(
    http_mcp, recorder, tool_name: str, suffix: str, payload_factory: Callable[[], dict[str, Any]], _key: str
) -> None:
    recorder.queue_json(go_envelope(payload_factory()))

    response = http_mcp.call_tool(tool_name, {"id": PET_ID})

    assert response.status_code == 200
    assert "mcp-session-id" not in {key.lower() for key in response.headers}
    assert response.json()["result"]["isError"] is False
    assert recorder.last_url.path == f"/api/v1/pets/{PET_ID}{suffix}"


def test_get_stats_over_stateless_http(http_mcp, recorder) -> None:
    recorder.queue_json(go_envelope(sample_stats()))

    response = http_mcp.call_tool("get_stats", {"top": 3})

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["totalRevenue"] == 3600
    assert recorder.params_of() == {"top": "3"}


@pytest.mark.parametrize("tool_name, payload", [
    ("get_pet", {"id": "nope"}),
    ("get_stats", {"top": 0}),
    ("list_pet_charges", {}),
])
def test_validation_error_over_stateless_http(http_mcp, tool_name: str, payload: dict[str, Any]) -> None:
    response = http_mcp.call_tool(tool_name, payload)

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    envelope = json.loads(result["content"][0]["text"])
    assert envelope["error"]["code"] == "VALIDATION_ERROR"


def test_health_lists_every_tool(http_mcp) -> None:
    payload = http_mcp.get("/health").json()
    assert payload["tools"] == EXPECTED_TOOLS


def test_list_pets_still_works_alongside_the_new_tools(http_mcp, recorder) -> None:
    """多工具共存时，阶段一的行为不能被破坏。"""
    recorder.queue_json(go_envelope(sample_data()))

    response = http_mcp.call_tool("list_pets", {"species": "犬"})

    assert response.json()["result"]["isError"] is False
    assert recorder.params_of() == {"species": "犬", "page": "1", "pageSize": "20"}
