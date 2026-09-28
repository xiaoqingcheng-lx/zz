"""REST 客户端测试：请求转发、重试、超时，以及错误码映射。

全部通过 ``httpx.MockTransport`` 打桩，**不会**访问真实 Go 服务。
"""

from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from pet_hospital_mcp.errors import ErrorCode, ToolFailure
from pet_hospital_mcp.rest_client import LIST_PETS_PATH, PetHospitalClient
from tests.helpers import go_envelope, sample_data, sample_pet

ALL_PARAMS: dict[str, Any] = {
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
    "page": 3,
    "pageSize": 50,
}


# ---------------------------------------------------------------------------
# 正常调用与参数转发
# ---------------------------------------------------------------------------


async def test_list_pets_forwards_path_and_every_query_param(
    recorder, make_client: Callable[..., PetHospitalClient]
) -> None:
    recorder.queue_json(go_envelope(sample_data()))
    client = make_client()

    result = await client.list_pets(ALL_PARAMS)
    await client.aclose()

    assert recorder.calls == 1
    request = recorder.requests[0]
    assert request.method == "GET"
    assert request.url.path == LIST_PETS_PATH == "/api/v1/pets"
    assert dict(request.url.params) == {
        "q": "肠胃炎",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "species": "犬",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "待就诊",
        # 客户端是纯转发层：这里直接传入的就是 int。
        # 经过 ListPetsInput 的浮点化版本由 tests/test_input_validation.py 的 as_query 覆盖。
        "min": "100",
        "max": "5000",
        "sortBy": "totalCost",
        "order": "desc",
        "page": "3",
        "pageSize": "50",
    }
    assert result.total == 1
    assert result.items[0].id == "PET-000001"
    assert result.totalCost == 180


async def test_success_output_maps_every_data_field(recorder, make_client) -> None:
    recorder.queue_json(go_envelope(sample_data()))
    client = make_client()
    data = await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert set(data.model_dump()) >= {"items", "total", "page", "pageSize", "totalPages", "totalCost"}
    pet = data.items[0]
    assert pet.ownerName == "张三"
    assert pet.records is not None and pet.records[0].diagnosis == "急性肠胃炎"
    assert pet.charges is not None and pet.charges[0].item == "血常规检查"


@pytest.mark.parametrize(
    "records, charges",
    [
        ([], []),  # 数组
        (None, None),  # Go 的 nil 切片会序列化成 null
        ([{"id": "R1", "diagnosis": "感冒", "doctor": "王医生"}], None),  # 混合
    ],
)
async def test_records_and_charges_accept_null_or_array(recorder, make_client, records, charges) -> None:
    pet = sample_pet(records=records, charges=charges)
    recorder.queue_json(go_envelope(sample_data(items=[pet])))
    client = make_client()
    data = await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert data.items[0].records == (None if records is None else data.items[0].records)
    if records is None:
        assert data.items[0].records is None
    else:
        assert isinstance(data.items[0].records, list)
    if charges is None:
        assert data.items[0].charges is None
    else:
        assert isinstance(data.items[0].charges, list)


# ---------------------------------------------------------------------------
# 上游 4xx / 5xx
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_4xx_maps_to_backend_api_error_and_is_not_retried(recorder, make_client, status) -> None:
    recorder.queue_json(go_envelope(None, code=status, message="参数不合法"), status=status)
    client = make_client(max_retries=3)

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    failure = excinfo.value
    assert failure.code is ErrorCode.BACKEND_API_ERROR
    assert failure.details["status"] == status
    assert "参数不合法" in failure.message
    assert recorder.calls == 1  # 4xx 不重试


async def test_5xx_is_retried_up_to_the_limit_then_reported(recorder, make_client) -> None:
    for _ in range(3):
        recorder.queue_json({"code": 500, "message": "内部错误", "data": None}, status=500)
    client = make_client(max_retries=2)

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_API_ERROR
    assert excinfo.value.details["status"] == 500
    assert recorder.calls == 3  # 1 次首发 + 2 次重试


async def test_5xx_then_success_recovers_within_retry_budget(recorder, make_client) -> None:
    recorder.queue_json({"code": 503, "message": "busy", "data": None}, status=503)
    recorder.queue_json(go_envelope(sample_data()))
    client = make_client(max_retries=2)

    data = await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert recorder.calls == 2
    assert data.total == 1


async def test_non_json_error_body_still_reports_readable_message(recorder, make_client) -> None:
    recorder.queue_raw(b"<html>502 Bad Gateway</html>", status=502, content_type="text/html")
    client = make_client(max_retries=0)

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_API_ERROR
    assert excinfo.value.details["status"] == 502


# ---------------------------------------------------------------------------
# 超时与连接异常
# ---------------------------------------------------------------------------


async def test_read_timeout_maps_to_backend_timeout(recorder, make_client) -> None:
    recorder.queue_exception(httpx.ReadTimeout("read timed out"))
    client = make_client(max_retries=0)

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_TIMEOUT
    assert excinfo.value.details["reason"] == "ReadTimeout"


async def test_connect_timeout_maps_to_backend_timeout(recorder, make_client) -> None:
    recorder.queue_exception(httpx.ConnectTimeout("connect timed out"))
    client = make_client(max_retries=0)

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_TIMEOUT


async def test_connect_error_maps_to_backend_unavailable(recorder, make_client) -> None:
    recorder.queue_exception(httpx.ConnectError("connection refused"))
    client = make_client(max_retries=0)

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_UNAVAILABLE
    assert excinfo.value.details["reason"] == "ConnectError"


async def test_transport_error_is_retried(recorder, make_client) -> None:
    recorder.queue_exception(httpx.ConnectError("connection refused"))
    recorder.queue_json(go_envelope(sample_data()))
    client = make_client(max_retries=1)

    data = await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert recorder.calls == 2
    assert data.total == 1


async def test_timeout_is_not_retried_when_budget_is_zero(recorder, make_client) -> None:
    recorder.queue_exception(httpx.ReadTimeout("read timed out"))
    client = make_client(max_retries=0)

    with pytest.raises(ToolFailure):
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert recorder.calls == 1


# ---------------------------------------------------------------------------
# 非法 JSON / 不符合数据模型
# ---------------------------------------------------------------------------


async def test_invalid_json_maps_to_backend_invalid_response(recorder, make_client) -> None:
    recorder.queue_raw(b"{not json at all", status=200)
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_INVALID_RESPONSE


async def test_non_object_payload_maps_to_backend_invalid_response(recorder, make_client) -> None:
    recorder.queue_json([1, 2, 3])
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_INVALID_RESPONSE


@pytest.mark.parametrize(
    "data",
    [
        {"items": [], "total": "abc", "page": 1, "pageSize": 20, "totalPages": 0, "totalCost": 0},
        {"items": [], "total": 1, "page": 1, "pageSize": 20, "totalPages": 0},  # 缺 totalCost
        {"items": {}, "total": 1, "page": 1, "pageSize": 20, "totalPages": 1, "totalCost": 0},
    ],
)
async def test_data_not_matching_model_maps_to_backend_invalid_response(recorder, make_client, data) -> None:
    recorder.queue_json(go_envelope(data))
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_INVALID_RESPONSE
    assert excinfo.value.details["fields"]


async def test_missing_data_maps_to_backend_invalid_response(recorder, make_client) -> None:
    recorder.queue_json({"code": 200, "message": "ok", "data": None})
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_INVALID_RESPONSE


async def test_envelope_code_not_200_maps_to_backend_api_error(recorder, make_client) -> None:
    recorder.queue_json(go_envelope(sample_data(), code=207, message="部分成功"))
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_API_ERROR
    assert excinfo.value.details["backendCode"] == 207


async def test_broken_envelope_maps_to_backend_invalid_response(recorder, make_client) -> None:
    recorder.queue_json({"message": "ok", "data": sample_data()})
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    assert excinfo.value.code is ErrorCode.BACKEND_INVALID_RESPONSE


# ---------------------------------------------------------------------------
# 不泄漏库细节
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "queue",
    [
        lambda r: r.queue_exception(httpx.ReadTimeout("read timed out")),
        lambda r: r.queue_exception(httpx.ConnectError("connection refused")),
        lambda r: r.queue_raw(b"{not json", status=200),
        lambda r: r.queue_json(go_envelope({"items": []})),
    ],
)
async def test_failures_never_leak_library_details(recorder, make_client, queue) -> None:
    queue(recorder)
    client = make_client()

    with pytest.raises(ToolFailure) as excinfo:
        await client.list_pets({"page": 1, "pageSize": 20})
    await client.aclose()

    lowered = (excinfo.value.message + str(excinfo.value.details)).lower()
    for forbidden in ("traceback", "pydantic", "httpx", "site-packages", "file \""):
        assert forbidden not in lowered, forbidden
