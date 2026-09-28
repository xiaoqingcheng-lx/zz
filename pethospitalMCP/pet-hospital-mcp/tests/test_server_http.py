"""无状态 Streamable HTTP 端到端测试。

这里起的是一个**真实**的 uvicorn 服务（后台线程 + 随机本机端口），
断言的是 2026-07-28 实际规定的发现 / 调用方式：

* 没有 ``initialize`` 握手；
* 不返回、也不要求 ``Mcp-Session-Id``；
* 发现用可选的 ``server/discover``；
* 每个请求自带 ``_meta``（协议版本 / 客户端信息 / 客户端能力）；
* 方法名与工具名走 ``Mcp-Method`` / ``Mcp-Name`` 请求头。

上游仍由 :class:`httpx.MockTransport` 打桩，不会访问真实 Go 服务。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from mcp import Client

from pet_hospital_mcp.errors import ErrorCode
from tests.helpers import (
    EXPECTED_TOOLS,
    PROTOCOL_VERSION,
    REQUEST_META,
    go_envelope,
    sample_data,
    sample_pet,
)

SESSION_HEADER = "mcp-session-id"


def _no_session_header(response: httpx.Response) -> bool:
    return SESSION_HEADER not in {key.lower() for key in response.headers}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_endpoint(http_mcp) -> None:
    response = http_mcp.get("/health")
    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["protocolVersion"] == PROTOCOL_VERSION == "2026-07-28"
    assert payload["sdkVersion"] == "2.0.0"
    assert payload["mcpEndpoint"] == "/mcp"
    assert payload["tools"] == EXPECTED_TOOLS
    assert payload["upstreamBaseUrl"] == "http://127.0.0.1:8080"


def test_health_probe_reports_upstream(http_mcp, recorder) -> None:
    recorder.queue_json(go_envelope(sample_data()))
    payload = http_mcp.get("/health", params={"probe": "upstream"}).json()
    assert payload["status"] == "ok"
    assert payload["upstream"]["status"] == "up"


def test_health_probe_reports_upstream_down(http_mcp, recorder) -> None:
    recorder.queue_exception(httpx.ConnectError("connection refused"))
    response = http_mcp.get("/health", params={"probe": "upstream"})
    assert response.status_code == 200  # MCP 服务本身仍然健康
    payload = response.json()
    assert payload["upstream"]["status"] == "down"
    assert payload["upstream"]["reason"] == "ToolFailure"


# ---------------------------------------------------------------------------
# server/discover（2026-07-28 的发现方式）
# ---------------------------------------------------------------------------


def test_server_discover_is_supported(http_mcp) -> None:
    response = http_mcp.discover()
    assert response.status_code == 200
    _no_session_header(response)

    result = response.json()["result"]
    assert result["supportedVersions"] == ["2026-07-28"]
    assert result["resultType"] == "complete"
    assert "tools" in result["capabilities"]


def test_discover_does_not_return_a_session_id(http_mcp) -> None:
    assert _no_session_header(http_mcp.discover())


def test_requests_are_self_describing(http_mcp) -> None:
    """2026-07-28 要求每个请求在 ``_meta`` 里自带协议版本，而不是靠握手协商。"""
    headers = http_mcp.mcp_headers("tools/list")
    body = {"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {}}
    response = http_mcp.post_raw("/mcp", json=body, headers=headers)

    assert response.status_code == 400
    error = response.json()["error"]
    assert "protocolVersion" in error["message"]


# ---------------------------------------------------------------------------
# tools/list & tools/call
# ---------------------------------------------------------------------------


def test_tools_call_success_returns_structured_content(http_mcp, recorder) -> None:
    recorder.queue_json(go_envelope(sample_data(total=1, totalCost=180)))

    response = http_mcp.call_tool("list_pets", {"species": "犬", "page": 1, "pageSize": 20})
    assert response.status_code == 200
    assert _no_session_header(response)

    result = response.json()["result"]
    assert result["isError"] is False
    assert result["resultType"] == "complete"
    assert list(result["structuredContent"]) == ["items", "total", "page", "pageSize", "totalPages", "totalCost"]
    assert result["structuredContent"]["total"] == 1
    assert result["structuredContent"]["items"][0]["ownerName"] == "张三"
    assert recorder.params_of() == {"species": "犬", "page": "1", "pageSize": "20"}


def test_tools_call_forwards_every_parameter_over_http(http_mcp, recorder) -> None:
    recorder.queue_json(go_envelope(sample_data()))
    arguments: dict[str, Any] = {
        "q": "肠胃炎",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "species": "犬",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "待就诊",
        "min": 100,
        "max": 5000,
        "sortBy": "totalCost",
        "order": "desc",
        "page": 2,
        "pageSize": 30,
    }
    response = http_mcp.call_tool("list_pets", arguments)
    assert response.status_code == 200

    assert recorder.requests[0].url.path == "/api/v1/pets"
    assert recorder.params_of() == {
        "q": "肠胃炎",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "species": "犬",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "待就诊",
        "min": "100.0",
        "max": "5000.0",
        "sortBy": "totalCost",
        "order": "desc",
        "page": "2",
        "pageSize": "30",
    }


def test_tools_call_records_charges_may_be_null(http_mcp, recorder) -> None:
    recorder.queue_json(go_envelope(sample_data(items=[sample_pet(records=None, charges=None)])))
    result = http_mcp.call_tool("list_pets", {}).json()["result"]
    pet = result["structuredContent"]["items"][0]
    assert pet["records"] is None
    assert pet["charges"] is None


def test_tools_call_missing_required_arguments_is_self_correctable(http_mcp) -> None:
    """参数校验失败必须是工具执行错误（isError），而不是 JSON-RPC 协议错误。"""
    response = http_mcp.call_tool("list_pets", {"species": "恐龙"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert "error" not in response.json()  # 不是协议层错误


# ---------------------------------------------------------------------------
# 上游异常经 HTTP 暴露为统一错误结构
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "queue, expected_code",
    [
        (lambda r: r.queue_json(go_envelope(None, code=404, message="not found"), status=404), ErrorCode.BACKEND_API_ERROR),
        (lambda r: r.queue_json({"code": 500, "message": "boom", "data": None}, status=500), ErrorCode.BACKEND_API_ERROR),
        (lambda r: r.queue_exception(httpx.ReadTimeout("read timed out")), ErrorCode.BACKEND_TIMEOUT),
        (lambda r: r.queue_exception(httpx.ConnectError("connection refused")), ErrorCode.BACKEND_UNAVAILABLE),
        (lambda r: r.queue_raw(b"{not json", status=200), ErrorCode.BACKEND_INVALID_RESPONSE),
        (lambda r: r.queue_json(go_envelope({"items": [], "total": "x"})), ErrorCode.BACKEND_INVALID_RESPONSE),
    ],
)
def test_upstream_failures_surface_as_unified_envelope(http_mcp, recorder, queue, expected_code) -> None:
    queue(recorder)
    envelope = http_mcp.error_payload("list_pets", {"page": 1, "pageSize": 20})

    assert envelope["error"]["code"] == expected_code.value
    assert envelope["error"]["message"]
    text = json.dumps(envelope, ensure_ascii=False).lower()
    for forbidden in ("traceback", "pydantic", "httpx", "site-packages", "file \""):
        assert forbidden not in text, forbidden


def test_upstream_5xx_is_retried_over_http(http_mcp_retrying, recorder) -> None:
    """客户端配了 2 次重试：连续两次 503 之后第三次成功。"""
    recorder.queue_json({"code": 503, "message": "busy", "data": None}, status=503)
    recorder.queue_json({"code": 503, "message": "busy", "data": None}, status=503)
    recorder.queue_json(go_envelope(sample_data()))

    result = http_mcp_retrying.call_tool("list_pets", {}).json()["result"]
    assert result["isError"] is False
    assert recorder.calls == 3


# ---------------------------------------------------------------------------
# 无状态：不握手、不建会话
# ---------------------------------------------------------------------------


def test_full_flow_works_without_initialize(http_mcp, recorder) -> None:
    """整条链路（发现 → 列工具 → 调工具）全程不发送 initialize。"""
    recorder.queue_json(go_envelope(sample_data()))

    discover = http_mcp.discover(rid=1)
    listing = http_mcp.list_tools(rid=2)
    call = http_mcp.call_tool("list_pets", {"species": "猫"}, rid=3)

    for response in (discover, listing, call):
        assert response.status_code == 200
        assert _no_session_header(response)
        assert "initialize" not in response.text

    names = [tool["name"] for tool in listing.json()["result"]["tools"]]
    assert names == EXPECTED_TOOLS

    assert call.json()["result"]["isError"] is False


def test_client_supplied_session_header_is_neither_required_nor_returned(http_mcp, recorder) -> None:
    """无状态模型下不存在会话：带上一个假 Session-Id 也不影响调用。"""
    recorder.queue_json(go_envelope(sample_data()))

    headers = http_mcp.mcp_headers("tools/call", "list_pets")
    headers[SESSION_HEADER] = "bogus-session-id"
    response = http_mcp.post_raw(
        "/mcp",
        json=http_mcp.mcp_body("tools/call", {"name": "list_pets", "arguments": {}}),
        headers=headers,
    )
    assert response.status_code == 200
    assert _no_session_header(response)


def test_calls_are_independent_across_requests(http_mcp, recorder) -> None:
    """任意两个请求之间没有共享状态：同样的入参得到同样的结果。"""
    for _ in range(2):
        recorder.queue_json(go_envelope(sample_data(total=7, totalCost=999)))

    first = http_mcp.call_tool("list_pets", {"q": "肠胃炎"}, rid=1).json()["result"]
    second = http_mcp.call_tool("list_pets", {"q": "肠胃炎"}, rid=2).json()["result"]

    assert first["structuredContent"] == second["structuredContent"]
    assert recorder.calls == 2


def test_invalid_json_literals_are_rejected(http_mcp) -> None:
    """JSON 里出现 NaN / Infinity 时不能悄悄通过。"""
    meta = json.dumps(REQUEST_META)
    for literal in ("NaN", "Infinity", "-Infinity"):
        body = (
            '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
            '{"name":"list_pets","arguments":{"min":' + literal + '},"_meta":' + meta + "}}"
        )
        response = http_mcp.post_raw(
            "/mcp",
            content=body.encode(),
            headers=http_mcp.mcp_headers("tools/call", "list_pets"),
        )
        assert response.status_code == 200, literal
        result = response.json()["result"]
        assert result["isError"] is True, literal
        envelope = json.loads(result["content"][0]["text"])
        assert envelope["error"]["code"] == ErrorCode.VALIDATION_ERROR.value, literal


# ---------------------------------------------------------------------------
# SDK 2.x 客户端端到端
# ---------------------------------------------------------------------------


def test_sdk_client_can_discover_and_call_over_http(http_mcp, recorder) -> None:
    recorder.queue_json(go_envelope(sample_data()))

    async def run() -> None:
        async with Client(http_mcp.mcp_url) as client:
            assert client.protocol_version == "2026-07-28"

            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == EXPECTED_TOOLS

            result = await client.call_tool("list_pets", {"species": "犬", "sortBy": "totalCost", "order": "desc"})
            assert result.is_error is False
            assert result.structured_content["total"] == 1

    import anyio

    anyio.run(run)
    assert recorder.params_of() == {"species": "犬", "sortBy": "totalCost", "order": "desc", "page": "1", "pageSize": "20"}
