"""测试辅助：上游假数据、记录型 MockTransport、本机 HTTP 服务封装。

放在独立模块（而不是 ``conftest.py``）里，测试文件可以直接 import 复用。
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
from typing import Any, Iterator

import httpx

BASE_URL = "http://127.0.0.1:8080"

#: 当前对外暴露的全部工具（1 个列表查询 + 5 个阶段二只读查询）。
#: 顺序由 ``pkgutil.iter_modules`` 的字典序决定，稳定可断言。
#: 这是整个测试套件里「工具集」的唯一定义处，改工具集时先改这里。
EXPECTED_TOOLS = [
    "get_pet",
    "get_pet_summary",
    "get_stats",
    "list_pet_charges",
    "list_pet_records",
    "list_pets",
]

#: 按 id 查单只宠物的四个工具。
ID_TOOLS = ["get_pet", "get_pet_summary", "list_pet_charges", "list_pet_records"]

#: 2026-07-28 的请求信封：每个请求自带协议版本 / 客户端信息 / 客户端能力。
PROTOCOL_VERSION = "2026-07-28"
REQUEST_META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


# ---------------------------------------------------------------------------
# 上游假数据
# ---------------------------------------------------------------------------


def sample_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "id": "REC-000001",
        "visitDate": "2026-08-01",
        "doctor": "李医生",
        "diagnosis": "急性肠胃炎",
        "symptoms": "呕吐、腹泻",
        "treatment": "补液+消炎",
        "prescription": ["阿莫西林", "蒙脱石散"],
        "weightKg": 12.5,
        "temperature": 39.1,
        "followUp": "一周后复查",
        "charge": 380,
        "createdAt": "2026-08-01T10:00:00+08:00",
    }
    record.update(overrides)
    return record


def sample_charge(**overrides: Any) -> dict[str, Any]:
    charge = {
        "id": "CHG-000001",
        "item": "血常规检查",
        "category": "检查",
        "amount": 180,
        "doctor": "李医生",
        "date": "2026-08-01",
        "note": "",
    }
    charge.update(overrides)
    return charge


def sample_pet(**overrides: Any) -> dict[str, Any]:
    pet = {
        "id": "PET-000001",
        "name": "旺财",
        "species": "犬",
        "breed": "金毛",
        "gender": "公",
        "ageMonths": 36,
        "color": "金色",
        "chipNo": "CN-000000000001",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "ownerAddr": "成都市武侯区",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "待就诊",
        "allergy": "无",
        "note": "",
        "records": [sample_record()],
        "charges": [sample_charge()],
        "totalCost": 180,
        "visitCount": 1,
        "createdAt": "2026-07-01T09:00:00+08:00",
        "updatedAt": "2026-08-01T10:00:00+08:00",
    }
    pet.update(overrides)
    return pet


def sample_data(**overrides: Any) -> dict[str, Any]:
    data = {
        "items": [sample_pet()],
        "total": 1,
        "page": 1,
        "pageSize": 20,
        "totalPages": 1,
        "totalCost": 180,
    }
    data.update(overrides)
    return data


def go_envelope(data: Any = None, *, code: int = 200, message: str = "ok") -> dict[str, Any]:
    """Go 服务的统一响应信封。"""
    return {"code": code, "message": message, "data": data, "time": "2026-09-17T10:00:00+08:00"}


# ---------------------------------------------------------------------------
# 阶段二接口的假数据
# ---------------------------------------------------------------------------

HISTORY_TEXT = "2026-08-01 李医生 急性肠胃炎 补液+消炎 处方:阿莫西林,蒙脱石散"


def sample_records_data(**overrides: Any) -> dict[str, Any]:
    """``GET /api/v1/pets/{id}/records`` 的 ``data``。"""
    data = {
        "petId": "PET-000001",
        "petName": "旺财",
        "ownerName": "张三",
        "count": 1,
        "records": [sample_record()],
        "historyText": HISTORY_TEXT,
    }
    data.update(overrides)
    return data


def sample_charges_data(**overrides: Any) -> dict[str, Any]:
    """``GET /api/v1/pets/{id}/charges`` 的 ``data``。"""
    data = {
        "petId": "PET-000001",
        "petName": "旺财",
        "count": 1,
        "charges": [sample_charge()],
        "totalCost": 180,
        "costByCategory": {"检查": 180},
    }
    data.update(overrides)
    return data


def sample_summary_data(**overrides: Any) -> dict[str, Any]:
    """``GET /api/v1/pets/{id}/summary`` 的 ``data``。"""
    data = {
        "id": "PET-000001",
        "name": "旺财",
        "species": "犬",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "待就诊",
        "totalCost": 180,
        "visitCount": 1,
        "chargeCount": 1,
        "costByCategory": {"检查": 180},
        "costByDoctor": {"李医生": 180},
        "maxSingleCharge": 180,
        "avgCostPerVisit": 180,
        "firstVisit": "2026-08-01",
        "lastVisit": "2026-08-01",
        "historyText": HISTORY_TEXT,
    }
    data.update(overrides)
    return data


def sample_stats(**overrides: Any) -> dict[str, Any]:
    """``GET /api/v1/stats`` 的 ``data``。"""
    data = {
        "totalPets": 2,
        "totalRecords": 4,
        "totalCharges": 6,
        "totalRevenue": 3600,
        "averageCost": 1800,
        "maxCost": 3420,
        "bySpecies": {"犬": 1, "猫": 1},
        "byStatus": {"待就诊": 1, "住院中": 1},
        "byDoctor": {"李医生": 1, "王医生": 1},
        "revenueByDoctor": {"李医生": 180, "王医生": 3420},
        "topSpenders": [sample_pet()],
        "logGarbagePct": 0,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# 日志抓取
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def captured_json_logs(level: int = logging.INFO) -> Iterator[io.StringIO]:
    """把本项目的日志以 JSON 形式收进内存，供断言。"""
    from pet_hospital_mcp.logging_config import JsonFormatter, get_logger

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = get_logger()
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        handler.close()


def json_log_records(stream: io.StringIO) -> list[dict[str, Any]]:
    """把抓到的日志文本解析成 dict 列表。"""
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 记录型 MockTransport
# ---------------------------------------------------------------------------


class UpstreamRecorder:
    """记录所有上游请求，并按队列返回预设响应（队列空则返回默认成功响应）。"""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._queue: list[Any] = []

    # -- 预设响应 ---------------------------------------------------------

    def queue_json(self, payload: Any, *, status: int = 200) -> UpstreamRecorder:
        self._queue.append(httpx.Response(status, json=payload))
        return self

    def queue_raw(self, body: bytes, *, status: int = 200, content_type: str = "application/json") -> UpstreamRecorder:
        self._queue.append(httpx.Response(status, content=body, headers={"content-type": content_type}))
        return self

    def queue_exception(self, exc: Exception) -> UpstreamRecorder:
        self._queue.append(exc)
        return self

    # -- MockTransport 入口 -----------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._queue:
            return httpx.Response(200, json=go_envelope(sample_data()))
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, httpx.Response)
        return item

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def last_url(self) -> httpx.URL:
        return self.requests[-1].url

    def params_of(self, index: int = 0) -> dict[str, str]:
        return dict(self.requests[index].url.params)


# ---------------------------------------------------------------------------
# 本机 HTTP 端到端封装
# ---------------------------------------------------------------------------


class HttpMCP:
    """跑在后台线程里的真实 uvicorn 服务 + 便于发原始 MCP 请求的小工具。"""

    def __init__(self, base_url: str, tools: list[str]) -> None:
        self.base_url = base_url
        self.mcp_url = f"{base_url}/mcp"
        self.tools = tools
        self._client = httpx.Client(base_url=base_url, trust_env=False, timeout=20.0)

    def close(self) -> None:
        self._client.close()

    # -- 普通 HTTP --------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._client.get(path, **kwargs)

    def post_raw(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._client.post(path, **kwargs)

    # -- MCP over HTTP ----------------------------------------------------

    def mcp_headers(self, method: str, name: str | None = None) -> dict[str, str]:
        """2026-07-28 的 Streamable HTTP 请求头：方法名与工具名走 HTTP 头，便于网关路由。"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Mcp-Method": method,
        }
        if name is not None:
            headers["Mcp-Name"] = name
        return headers

    def mcp_body(self, method: str, params: Any = None, *, rid: int = 1) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": {**(params or {}), "_meta": dict(REQUEST_META)},
        }

    def mcp(self, method: str, params: Any = None, *, name: str | None = None, rid: int = 1) -> httpx.Response:
        """发一个 2026-07-28 风格的 MCP 请求（自带 _meta，不再有 initialize 握手）。"""
        return self._client.post(
            "/mcp",
            json=self.mcp_body(method, params, rid=rid),
            headers=self.mcp_headers(method, name),
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any], *, rid: int = 1) -> httpx.Response:
        return self.mcp("tools/call", {"name": tool_name, "arguments": arguments}, name=tool_name, rid=rid)

    def list_tools(self, *, rid: int = 1) -> httpx.Response:
        return self.mcp("tools/list", {}, rid=rid)

    def discover(self, *, rid: int = 1) -> httpx.Response:
        return self.mcp("server/discover", {}, rid=rid)

    def error_payload(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用工具并解析出统一错误信封。"""
        response = self.call_tool(tool_name, arguments)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["isError"] is True, result
        texts = [block["text"] for block in result["content"] if block.get("type") == "text"]
        assert len(texts) == 1, texts
        return json.loads(texts[0])
