"""标准库 JSON 日志，附带递归脱敏。

日志约定
--------
每次工具调用输出**一行** JSON，至少包含
``timestamp`` / ``tool_name`` / ``params`` / ``status`` / ``duration_ms``。

脱敏
----
``ownerPhone`` / ``ownerAddr`` / ``chipNo`` 及其 snake_case 写法
（``owner_phone`` / ``owner_addr`` / ``chip_no``）在写日志前会被**递归**替换成
``"***"``，无论它们出现在字典、嵌套字典还是数组里。比较时忽略大小写与下划线，
所以 ``OwnerPhone``、``ownerphone`` 同样会被脱敏。

日志写 stderr：stdio 传输下 stdout 就是协议线，任何多余的 stdout 输出都会破坏协议。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, Mapping

__all__ = [
    "JsonFormatter",
    "REDACTED",
    "SENSITIVE_KEYS",
    "configure_logging",
    "get_logger",
    "redact",
]

#: 被替换后的占位符。
REDACTED = "***"

#: 需要脱敏的字段名（比较前会先做归一化：转小写 + 去掉下划线与连字符）。
SENSITIVE_KEYS = frozenset({"ownerphone", "owneraddr", "chipno"})

_NORMALIZE = re.compile(r"[_\-]")

LOGGER_NAME = "pet_hospital_mcp"

#: httpx / httpcore 会以 INFO 级别打印**完整请求 URL**，而 URL 的查询串里可能带
#: 敏感参数（如 ``?ownerPhone=13800142432``）。脱敏只作用于我们自己的结构化字段，
#: 无法改写第三方库已经拼好的成品字符串，因此把这两个 logger 抬到 WARNING：
#: 既堵住敏感数据外泄，又保留真正需要关注的告警。
_NOISY_LOGGERS = ("httpx", "httpcore")


def _normalize_key(key: object) -> str:
    return _NORMALIZE.sub("", str(key)).lower()


def redact(value: Any, *, _depth: int = 0) -> Any:
    """递归脱敏：字典按键名判断，列表逐项下钻，其它类型原样返回。"""
    if _depth > 12:  # 防御异常深的结构
        return value
    if isinstance(value, Mapping):
        return {
            key: (REDACTED if _normalize_key(key) in SENSITIVE_KEYS else redact(item, _depth=_depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, _depth=_depth + 1) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """把日志记录渲染成单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - logging API
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, Mapping):
            # 再脱敏一次：即使调用方忘了，也不会把敏感字段写进日志。
            payload.update(redact(dict(extra)))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """配置根 logger 输出 JSON 到 stderr（幂等）。"""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        # 只清理本模块自己装过的 handler，避免踩到宿主进程（例如 uvicorn）的配置。
        if getattr(handler, "_pet_hospital_json", False):
            root.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler._pet_hospital_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    # 第三方库的 INFO 日志可能把敏感查询参数原样带出来（见 _NOISY_LOGGERS 注释）。
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))


def get_logger(name: str | None = None) -> logging.Logger:
    """取本项目的 logger。"""
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")


def log_tool_call(
    *,
    tool_name: str,
    params: Mapping[str, Any] | None,
    status: str,
    duration_ms: float,
    logger: logging.Logger | None = None,
    **extra: Any,
) -> None:
    """输出一次工具调用的标准日志行。"""
    (logger or get_logger("tool")).info(
        "tool_call",
        extra={
            "extra_fields": {
                "tool_name": tool_name,
                "params": dict(params or {}),
                "status": status,
                "duration_ms": round(duration_ms, 3),
                **extra,
            }
        },
    )
