"""上游 Go 宠物医院 REST API 的 HTTP 客户端。

职责边界
--------
* 只用 HTTP 调用 Go 服务，**绝不**触碰它的代码或数据文件。
* 统一带上超时与有限重试。
* 把 httpx / Pydantic / Python 的原始异常**全部**翻译成 :class:`ToolFailure` +
  统一错误码，绝不把堆栈或库的类型泄漏给 MCP 客户端。

错误码映射（本模块是唯一定义处）
--------------------------------
============================ =========================================
情况                          错误码
============================ =========================================
超时（含连接超时）              ``BACKEND_TIMEOUT``
连接被拒 / 网络不可达           ``BACKEND_UNAVAILABLE``
HTTP 4xx / 5xx                 ``BACKEND_API_ERROR``
信封 ``code != 200``           ``BACKEND_API_ERROR``
响应不是合法 JSON               ``BACKEND_INVALID_RESPONSE``
响应不符合数据模型              ``BACKEND_INVALID_RESPONSE``
其它未预期异常                  ``INTERNAL_ERROR``
============================ =========================================
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import ErrorCode, ToolFailure
from .logging_config import get_logger
from .upstream import (
    HospitalStats,
    ListPetsData,
    PetChargesData,
    PetRecord,
    PetRecordsData,
    PetSummaryData,
)

__all__ = ["LIST_PETS_PATH", "STATS_PATH", "PetHospitalClient"]

logger = get_logger("rest_client")

#: 上游路径。
LIST_PETS_PATH = "/api/v1/pets"
STATS_PATH = "/api/v1/stats"
RECORDS_PATH = "/api/v1/pets/{pet_id}/records"
CHARGES_PATH = "/api/v1/pets/{pet_id}/charges"
SUMMARY_PATH = "/api/v1/pets/{pet_id}/summary"

_ModelT = TypeVar("_ModelT", bound=BaseModel)

#: 写进错误 details 的上游消息截断长度。
_MESSAGE_LIMIT = 300


class _GoEnvelope(BaseModel):
    """Go 服务的统一响应信封：``{code, message, data, time}``。"""

    model_config = ConfigDict(extra="ignore")

    code: int
    message: str = ""
    data: Any = None
    time: str | None = None


def _clip(text: str, limit: int = _MESSAGE_LIMIT) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


def _backend_message(response: httpx.Response) -> str:
    """尽力从错误响应里取出可读消息，失败则退回 HTTP 原因短语。"""
    try:
        payload = response.json()
    except ValueError:
        body = response.text
        return _clip(body) if body.strip() else response.reason_phrase
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if isinstance(message, str) and message.strip():
            return _clip(message)
        if isinstance(message, dict) and isinstance(message.get("message"), str):
            return _clip(message["message"])
    return response.reason_phrase


class PetHospitalClient:
    """调用 Go 宠物医院 REST API 的异步客户端。"""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        trust_env: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_seconds: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, int(max_retries))
        self._backoff = max(0.0, float(backoff_seconds))
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            trust_env=trust_env,
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )

    # -- 生命周期 ---------------------------------------------------------

    async def aclose(self) -> None:
        """关闭底层连接池。"""
        await self._client.aclose()

    async def __aenter__(self) -> PetHospitalClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- 内部：带重试的请求 -----------------------------------------------

    def _is_retryable(self, response: httpx.Response | None, exc: Exception | None) -> bool:
        """只有「可能瞬时恢复」的失败才重试：网络类异常与 5xx。4xx 不重试。"""
        if exc is not None:
            return isinstance(exc, (httpx.TransportError,))
        assert response is not None
        return response.status_code >= 500

    def _sleep_for_attempt(self, attempt: int) -> float:
        return self._backoff * (2**attempt)

    async def _get(self, path: str, params: Mapping[str, Any]) -> httpx.Response:
        last_exc: Exception | None = None
        last_response: httpx.Response | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(path, params=dict(params))
            except httpx.HTTPError as exc:  # 包含超时与传输层错误
                last_exc, last_response = exc, None
                if attempt < self.max_retries and self._is_retryable(None, exc):
                    logger.warning(
                        "upstream request failed, retrying",
                        extra={
                            "extra_fields": {
                                "path": path,
                                "attempt": attempt + 1,
                                "max_retries": self.max_retries,
                                "error": type(exc).__name__,
                            }
                        },
                    )
                    await asyncio.sleep(self._sleep_for_attempt(attempt))
                    continue
                raise self._translate_transport_error(exc) from exc

            last_exc, last_response = None, response
            if response.status_code < 500:
                return response
            if attempt < self.max_retries and self._is_retryable(response, None):
                logger.warning(
                    "upstream returned 5xx, retrying",
                    extra={
                        "extra_fields": {
                            "path": path,
                            "status": response.status_code,
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries,
                        }
                    },
                )
                await asyncio.sleep(self._sleep_for_attempt(attempt))
                continue
            return response

        # 理论上不可达：循环内必然 return 或 raise。
        if last_response is not None:
            return last_response
        raise self._translate_transport_error(last_exc)  # pragma: no cover

    @staticmethod
    def _translate_transport_error(exc: Exception | None) -> ToolFailure:
        if isinstance(exc, httpx.TimeoutException):
            return ToolFailure(
                ErrorCode.BACKEND_TIMEOUT,
                "调用上游宠物医院服务超时，请稍后重试。",
                {"reason": type(exc).__name__},
            )
        if isinstance(exc, httpx.ConnectError):
            return ToolFailure(
                ErrorCode.BACKEND_UNAVAILABLE,
                "无法连接上游宠物医院服务，请确认它已启动且地址正确。",
                {"reason": type(exc).__name__},
            )
        if isinstance(exc, httpx.TransportError):
            return ToolFailure(
                ErrorCode.BACKEND_UNAVAILABLE,
                "与上游宠物医院服务的通信失败。",
                {"reason": type(exc).__name__},
            )
        return ToolFailure(
            ErrorCode.INTERNAL_ERROR,
            "适配器内部错误。",
            {"reason": type(exc).__name__ if exc is not None else "unknown"},
        )

    # -- 具体接口 ---------------------------------------------------------
    #
    # 每个方法只有一行：给出上游路径、查询参数、出参模型和中文名，
    # 剩下的「取数 → 判状态 → 解析信封 → 校验 data」由 _fetch 统一处理，
    # 保证所有工具共享同一套超时、重试与错误码语义。

    async def list_pets(self, query: Mapping[str, Any]) -> ListPetsData:
        """``GET /api/v1/pets``：过滤 + 排序 + 分页。"""
        return await self._fetch(LIST_PETS_PATH, query, ListPetsData, "列表查询")

    async def get_pet(self, pet_id: str) -> PetRecord:
        """``GET /api/v1/pets/{id}``：按主键查单只宠物。id 不存在时上游返回 404。"""
        return await self._fetch(f"{LIST_PETS_PATH}/{pet_id}", {}, PetRecord, "宠物档案")

    async def list_pet_records(self, pet_id: str) -> PetRecordsData:
        """``GET /api/v1/pets/{id}/records``：单只宠物的历史病历。"""
        return await self._fetch(RECORDS_PATH.format(pet_id=pet_id), {}, PetRecordsData, "历史病历")

    async def list_pet_charges(self, pet_id: str) -> PetChargesData:
        """``GET /api/v1/pets/{id}/charges``：单只宠物的消费明细。"""
        return await self._fetch(CHARGES_PATH.format(pet_id=pet_id), {}, PetChargesData, "消费明细")

    async def get_pet_summary(self, pet_id: str) -> PetSummaryData:
        """``GET /api/v1/pets/{id}/summary``：单只宠物的费用与就诊汇总。"""
        return await self._fetch(SUMMARY_PATH.format(pet_id=pet_id), {}, PetSummaryData, "费用汇总")

    async def get_stats(self, top: int) -> HospitalStats:
        """``GET /api/v1/stats?top=N``：全医院经营统计（含消费排行）。"""
        return await self._fetch(STATS_PATH, {"top": top}, HospitalStats, "经营统计")

    # -- 公共取数流程 -----------------------------------------------------

    async def _fetch(
        self,
        path: str,
        params: Mapping[str, Any],
        model: type[_ModelT],
        what: str,
    ) -> _ModelT:
        response = await self._get(path, params)
        self._raise_for_status(response)
        payload = self._parse_json(response)
        envelope = self._parse_envelope(payload, response)
        if envelope.code != 200:
            raise ToolFailure(
                ErrorCode.BACKEND_API_ERROR,
                _clip(envelope.message) or "上游服务返回了失败状态。",
                {"status": response.status_code, "backendCode": envelope.code},
            )
        return self._parse_data(envelope.data, response, model, what)

    # -- 解析 -------------------------------------------------------------

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """HTTP 层失败优先判：状态码先于响应体解析，避免把 5xx 误判成响应格式问题。"""
        if response.status_code >= 400:
            raise ToolFailure(
                ErrorCode.BACKEND_API_ERROR,
                _backend_message(response),
                {"status": response.status_code},
            )

    @staticmethod
    def _parse_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ToolFailure(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "上游服务返回了无法解析的响应体（不是合法 JSON）。",
                {"status": response.status_code, "contentType": response.headers.get("content-type", "")},
            ) from exc

    @staticmethod
    def _parse_envelope(payload: Any, response: httpx.Response) -> _GoEnvelope:
        if not isinstance(payload, dict):
            raise ToolFailure(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "上游服务返回的响应体不是预期的 JSON 对象。",
                {"status": response.status_code, "payloadType": type(payload).__name__},
            )
        try:
            return _GoEnvelope.model_validate(payload)
        except ValidationError as exc:
            raise ToolFailure(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "上游服务的响应信封不符合约定结构。",
                {"status": response.status_code, "fields": _field_names(exc)},
            ) from exc

    @staticmethod
    def _parse_data(data: Any, response: httpx.Response, model: type[_ModelT], what: str) -> _ModelT:
        if data is None:
            raise ToolFailure(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "上游服务的响应信封里缺少 data。",
                {"status": response.status_code},
            )
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise ToolFailure(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                f"上游服务返回的数据不符合「{what}」的响应模型。",
                {"status": response.status_code, "fields": _field_names(exc)},
            ) from exc


def _field_names(exc: ValidationError, limit: int = 20) -> list[str]:
    names: list[str] = []
    for err in exc.errors(include_url=False, include_input=False)[:limit]:
        names.append(".".join(str(part) for part in err.get("loc", ())) or "(root)")
    return names
