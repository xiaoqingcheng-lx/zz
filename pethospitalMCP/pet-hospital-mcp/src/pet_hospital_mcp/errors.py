"""统一结构化错误约定。

本模块是整个适配器唯一的错误出口，负责三件事：

1. 定义全部错误码（``ErrorCode``）。
2. 定义对 MCP 客户端可见的错误信封模型（``ErrorEnvelope`` / ``ErrorDetail``），
   线格式固定为::

       {"error": {"code": "ERROR_CODE", "message": "可读错误信息", "details": {}}}

3. 提供把内部异常转成「工具执行错误」的助手（``failure`` / ``tool_failure_text``）。

设计要点
--------
MCP Python SDK 2.x 里，工具失败**不再**由业务代码手搓 ``CallToolResult(isError=True)``：
业务代码抛出 :class:`mcp.server.mcpserver.exceptions.ToolError`，由 SDK 统一标记为
``is_error=True`` 的工具执行错误（``MCPError`` 则会被当成 JSON-RPC 协议错误，模型看不到，
因此本适配器一律不使用 ``MCPError``）。

但 SDK 会把异常包装成 ``"Error executing tool <name>: <原始 message>"``，
并且它自己的参数校验失败会原样透出 Pydantic 报错文本。为了让客户端永远只看到统一结构，
工具层抛出的信封文本会带上下面的标记，再由 :mod:`pet_hospital_mcp.middleware` 在结果层
还原成干净的信封 JSON。
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, NoReturn

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "ErrorCode",
    "ErrorDetail",
    "ErrorEnvelope",
    "ENVELOPE_MARKER",
    "ToolFailure",
    "envelope_from_text",
    "error_json",
    "failure",
    "tool_failure_text",
    "validation_details",
]


class ErrorCode(StrEnum):
    """适配器对客户端暴露的全部错误码。"""

    #: 工具输入不合法（未知字段、类型错误、枚举越界、区间越界、min > max 等）。
    VALIDATION_ERROR = "VALIDATION_ERROR"
    #: 调用上游超时（连接超时 / 读超时 / 写超时 / 连接池超时）。
    BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
    #: 上游不可达或连接被拒绝（服务没启动、端口不通、连接被重置）。
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    #: 上游应答了，但业务上是失败的（HTTP 4xx/5xx，或信封 code != 200）。
    BACKEND_API_ERROR = "BACKEND_API_ERROR"
    #: 上游应答了，但响应体不是合法 JSON，或不符合约定的数据模型。
    BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
    #: 适配器自身未预期的错误（兜底）。永远不向客户端暴露堆栈。
    INTERNAL_ERROR = "INTERNAL_ERROR"


#: 出现在 ``ToolError`` 文本里的信封标记，用于在结果层可靠地还原信封 JSON。
ENVELOPE_MARKER = "[[pet-hospital-mcp:error-envelope]]"


class ErrorDetail(BaseModel):
    """错误信封的 ``error`` 部分。"""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode = Field(description="机器可读的错误码。")
    message: str = Field(description="面向调用方（含模型）的可读错误信息，不含堆栈。")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="补充信息，例如字段级校验原因、上游 HTTP 状态码。",
    )


class ErrorEnvelope(BaseModel):
    """对客户端统一的错误结构。"""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class ToolFailure(Exception):
    """带错误码的业务/上游失败。

    只在本适配器内部流转；到达 MCP 边界前会被 :func:`failure` 转成工具执行错误。
    """

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    @property
    def envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(error=ErrorDetail(code=self.code, message=self.message, details=self.details))


def error_json(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> str:
    """把错误码渲染成线上使用的信封 JSON 字符串。"""
    envelope = ErrorEnvelope(error=ErrorDetail(code=code, message=message, details=details or {}))
    return json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False)


def tool_failure_text(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> str:
    """渲染带标记的信封文本，供 :func:`failure` 抛给 SDK。"""
    return f"{ENVELOPE_MARKER}{error_json(code, message, details)}"


def failure(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> NoReturn:
    """抛出带统一信封的 :class:`ToolError`（SDK 会标记为 ``is_error=True`` 的工具执行错误）。"""
    raise ToolError(tool_failure_text(code, message, details))


def validation_details(exc: ValidationError, *, limit: int = 20) -> dict[str, Any]:
    """把 Pydantic 校验错误归一化成**我们自己的**字段级结构（不暴露 Pydantic 原文）。

    返回形如 ``{"fields": [{"field": "pageSize", "reason": "..."}]}`` 的 dict，
    既避免泄漏 SDK/Pydantic 内部信息，又让模型能据此自我纠正。
    """
    fields: list[dict[str, str]] = []
    for err in exc.errors(include_url=False, include_input=False)[:limit]:
        location = ".".join(str(part) for part in err.get("loc", ())) or "(body)"
        reason = str(err.get("msg", "invalid value"))
        # 枚举越界时把允许值一并带上，模型才知道什么是合法的。
        # Pydantic 的 msg 在不同版本里有时已内联允许值（例如 literal_error），
        # 已包含就不再追加，避免出现 "Input should be 'a' or 'b': 'a' or 'b'" 这种重复。
        expected = err.get("ctx", {}).get("expected")
        if expected and str(expected) not in reason:
            reason = f"{reason}: {expected}"
        fields.append({"field": location, "reason": reason})
    return {"fields": fields}


def envelope_from_text(text: str) -> str | None:
    """从 SDK 包装过的错误文本里还原信封 JSON；不是信封则返回 ``None``。

    SDK 会把异常渲染成 ``"Error executing tool <name>: <message>"``，其中 ``<message>``
    就是我们抛出的 :data:`ENVELOPE_MARKER` + 信封 JSON。这里按标记切分并做一次严格校验，
    只有确实解析成合法信封才认账，避免误伤其它错误文本。
    """
    index = text.rfind(ENVELOPE_MARKER)
    if index == -1:
        return None
    candidate = text[index + len(ENVELOPE_MARKER) :].strip()
    try:
        payload = json.loads(candidate)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return None
    if payload["error"].get("code") not in {code.value for code in ErrorCode}:
        return None
    return json.dumps(payload, ensure_ascii=False)
