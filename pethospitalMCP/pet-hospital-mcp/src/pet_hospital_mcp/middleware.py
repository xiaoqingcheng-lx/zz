"""MCP 结果层契约加固。

SDK 2.x 的两个行为会破坏「严格校验 + 统一错误结构」的要求，本中间件专门处理：

1. **参数模型是宽松的。** ``MCPServer`` 由函数签名生成的参数模型既不拒绝未知字段
   （``create_model(..., __config__=ConfigDict(from_attributes=True))``，没有
   ``extra="forbid"``），也会做强转（``page="2"`` 会被接受）。而且未知字段在调用业务函数
   之前就被丢掉了，工具自己看不到。所以必须在**进入 SDK 处理前**用严格模型校验原始
   ``arguments``。
2. **错误文本会泄漏。** SDK 把异常渲染成 ``"Error executing tool <name>: <原始消息>"``，
   Pydantic 校验失败时会把报错文本连同 ``errors.pydantic.dev`` 链接一起写给客户端。
   本中间件在结果层把任何 ``isError=True`` 重写成统一错误信封。

中间件同时承担**唯一**的工具调用日志点：一次调用一行 JSON，含
``timestamp`` / ``tool_name`` / ``params`` / ``status`` / ``duration_ms``。
"""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from pydantic import BaseModel, ValidationError

from .errors import ErrorCode, envelope_from_text, error_json, validation_details
from .logging_config import log_tool_call

__all__ = ["ContractMiddleware"]

#: SDK 包装 Pydantic 校验错误时的特征串，用于把「框架侧入参校验失败」归类为 VALIDATION_ERROR。
_FRAMEWORK_VALIDATION_MARKERS = (
    "validation error for",
    "errors.pydantic.dev",
    "Field required",
    "Extra inputs are not permitted",
)

#: 请求上下文中承载原始入参的键。
_NAME_KEY = "name"
_ARGUMENTS_KEY = "arguments"

_TOOLS_LIST = "tools/list"
_TOOLS_CALL = "tools/call"


def _server_info_meta(server_name: str, server_version: str) -> dict[str, Any] | None:
    """尽力复刻 SDK 的 ``_meta.serverInfo`` 标记（常量缺失时跳过）。"""
    try:
        from mcp.types import SERVER_INFO_META_KEY  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - 常量名随 SDK 版本变动
        return None
    return {SERVER_INFO_META_KEY: {"name": server_name, "version": server_version}}


class ContractMiddleware:
    """严格入参校验 + 统一错误结构 + 工具调用日志。"""

    def __init__(
        self,
        models: Mapping[str, type[BaseModel]],
        *,
        server_name: str = "pet-hospital-mcp",
        server_version: str = "",
    ) -> None:
        self._models: dict[str, type[BaseModel]] = dict(models)
        self._server_name = server_name
        self._server_version = server_version
        self._meta = _server_info_meta(server_name, server_version)

    # -- 入口 -------------------------------------------------------------

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        method = getattr(ctx, "method", "")
        if method == _TOOLS_LIST:
            return self._declare_closed_input_schemas(await call_next(ctx))
        if method != _TOOLS_CALL:
            return await call_next(ctx)

        params: Mapping[str, Any] = getattr(ctx, "params", None) or {}
        tool_name = str(params.get(_NAME_KEY, ""))
        arguments = params.get(_ARGUMENTS_KEY) or {}
        if not isinstance(arguments, Mapping):
            arguments = {}

        rejection = self._reject_invalid_arguments(tool_name, arguments)
        if rejection is not None:
            return rejection

        started = time.perf_counter()
        result = await call_next(ctx)
        duration_ms = (time.perf_counter() - started) * 1000

        normalized, status = self._normalize_failure(result)
        log_tool_call(tool_name=tool_name, params=arguments, status=status, duration_ms=duration_ms)
        return normalized

    # -- 输入校验 ---------------------------------------------------------

    def _reject_invalid_arguments(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
        """严格校验原始入参；不合法时直接返回统一错误结果，不再进入工具。"""
        model = self._models.get(tool_name)
        if model is None:
            return None
        try:
            model.model_validate(dict(arguments))
        except ValidationError as exc:
            log_tool_call(
                tool_name=tool_name,
                params=arguments,
                status=ErrorCode.VALIDATION_ERROR.value,
                duration_ms=0.0,
            )
            return self._failure_result(ErrorCode.VALIDATION_ERROR, "输入参数校验失败。", validation_details(exc))
        return None

    # -- 错误结构 ---------------------------------------------------------

    def _normalize_failure(self, result: Any) -> tuple[Any, str]:
        """把 ``isError=True`` 的结果重写成统一信封，返回 ``(结果, 状态)``。"""
        payload = self._as_dict(result)
        if payload is None or not payload.get("isError"):
            return result, "ok"

        texts = [
            block.get("text", "")
            for block in payload.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        raw = "\n".join(texts)

        envelope = envelope_from_text(raw)
        if envelope is not None:
            code = json.loads(envelope)["error"]["code"]
        elif any(marker in raw for marker in _FRAMEWORK_VALIDATION_MARKERS):
            code = ErrorCode.VALIDATION_ERROR.value
            envelope = error_json(ErrorCode.VALIDATION_ERROR, "输入参数校验失败。")
        else:
            code = ErrorCode.INTERNAL_ERROR.value
            envelope = error_json(ErrorCode.INTERNAL_ERROR, "适配器内部错误。")

        payload["content"] = [{"type": "text", "text": envelope}]
        payload["isError"] = True
        payload.setdefault("resultType", "complete")
        return payload, code

    def _failure_result(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": [{"type": "text", "text": error_json(code, message, details)}],
            "isError": True,
            "resultType": "complete",
        }
        if self._meta:
            payload["_meta"] = dict(self._meta)
        return payload

    @staticmethod
    def _as_dict(result: Any) -> dict[str, Any] | None:
        """中间件看到的既可能是已经序列化好的 dict，也可能是 Pydantic 模型。"""
        if isinstance(result, dict):
            return dict(result)
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json", by_alias=True, exclude_none=True)
        return None

    # -- 工具清单契约 -----------------------------------------------------

    def _declare_closed_input_schemas(self, result: Any) -> Any:
        """给被严格模型约束的工具，在 JSON Schema 上补 ``additionalProperties: false``。

        SDK 生成的扁平参数 schema 不声明该字段，但契约中间件确实会拒绝未知字段；
        补上它，schema 与真实行为才一致。
        """
        payload = self._as_dict(result)
        if payload is None:
            return result
        for tool in payload.get("tools", []) or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("name") not in self._models:
                continue
            self._close_schema(tool.get("inputSchema"))
        return payload

    @staticmethod
    def _close_schema(schema: Any) -> None:
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "object" and "additionalProperties" not in schema:
            schema["additionalProperties"] = False
        for definition in (schema.get("$defs") or {}).values():
            ContractMiddleware._close_schema(definition)
