"""日志格式与递归脱敏测试。"""

from __future__ import annotations

import io
import json
import logging

import pytest
from mcp import Client

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.logging_config import (
    JsonFormatter,
    configure_logging,
    get_logger,
    log_tool_call,
    redact,
)
from pet_hospital_mcp.server import build_server
from tests.helpers import captured_json_logs

PHONE = "13800001111"
ADDR = "成都市武侯区科华北路 1 号"
CHIP = "CN-000000000001"


# ---------------------------------------------------------------------------
# 递归脱敏
# ---------------------------------------------------------------------------


def test_redacts_sensitive_keys_at_top_level() -> None:
    result = redact({"ownerPhone": PHONE, "ownerAddr": ADDR, "chipNo": CHIP, "name": "旺财"})
    assert result == {"ownerPhone": "***", "ownerAddr": "***", "chipNo": "***", "name": "旺财"}


@pytest.mark.parametrize(
    "key",
    ["ownerPhone", "owner_phone", "ownerphone", "OwnerPhone", "OWNER_PHONE", "owner-phone"],
)
def test_redaction_is_case_and_separator_insensitive_for_phone(key: str) -> None:
    assert redact({key: PHONE})[key] == "***"


@pytest.mark.parametrize("key", ["ownerAddr", "owner_addr", "owneraddr", "OWNER_ADDR"])
def test_redaction_covers_owner_address_variants(key: str) -> None:
    assert redact({key: ADDR})[key] == "***"


@pytest.mark.parametrize("key", ["chipNo", "chip_no", "chipno", "CHIP_NO"])
def test_redaction_covers_chip_number_variants(key: str) -> None:
    assert redact({key: CHIP})[key] == "***"


def test_redaction_is_recursive() -> None:
    payload = {
        "items": [
            {"name": "旺财", "ownerPhone": PHONE, "nested": {"chipNo": CHIP}},
            {"name": "咪咪", "details": [{"owner_addr": ADDR}, {"chip_no": CHIP}]},
        ],
        "meta": {"page": 1},
    }
    result = redact(payload)

    assert result["items"][0]["ownerPhone"] == "***"
    assert result["items"][0]["nested"]["chipNo"] == "***"
    assert result["items"][1]["details"][0]["owner_addr"] == "***"
    assert result["items"][1]["details"][1]["chip_no"] == "***"
    assert result["items"][0]["name"] == "旺财"
    assert result["meta"] == {"page": 1}

    dumped = json.dumps(result, ensure_ascii=False)
    for secret in (PHONE, ADDR, CHIP):
        assert secret not in dumped


def test_redaction_keeps_non_dict_values() -> None:
    assert redact("旺财") == "旺财"
    assert redact(42) == 42
    assert redact(None) is None
    assert redact([1, "a"]) == [1, "a"]


# ---------------------------------------------------------------------------
# 日志行格式
# ---------------------------------------------------------------------------


def test_log_tool_call_emits_required_fields() -> None:
    with captured_json_logs() as stream:
        log_tool_call(
            tool_name="list_pets",
            params={"species": "犬", "page": 1},
            status="ok",
            duration_ms=12.3456,
        )

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])

    assert set(record) >= {"timestamp", "tool_name", "params", "status", "duration_ms"}
    assert record["tool_name"] == "list_pets"
    assert record["params"] == {"species": "犬", "page": 1}
    assert record["status"] == "ok"
    assert record["duration_ms"] == pytest.approx(12.346, abs=0.01)
    assert record["timestamp"].startswith("20")


def test_log_tool_call_redacts_sensitive_params() -> None:
    with captured_json_logs() as stream:
        log_tool_call(
            tool_name="list_pets",
            params={"ownerPhone": PHONE, "q": "旺财"},
            status="ok",
            duration_ms=1.0,
        )

    text = stream.getvalue()
    assert PHONE not in text
    assert json.loads(text)["params"] == {"ownerPhone": "***", "q": "旺财"}


def test_transport_loggers_cannot_leak_sensitive_query_strings() -> None:
    """httpx / httpcore 的 INFO 日志会原样打印带查询串的 URL，必须被压到 WARNING 以上。

    否则 ``GET /api/v1/pets?ownerPhone=138...`` 会绕过结构化脱敏直接进日志。
    """
    root = logging.getLogger()
    previous_root_level = root.level
    previous_levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    try:
        configure_logging("INFO")
        assert logging.getLogger("httpx").level >= logging.WARNING
        assert logging.getLogger("httpcore").level >= logging.WARNING

        root.addHandler(handler)
        logging.getLogger("httpx").info(
            'HTTP Request: GET http://127.0.0.1:8080/api/v1/pets?ownerPhone=%s "HTTP/1.1 200 OK"',
            PHONE,
        )
    finally:
        root.removeHandler(handler)
        handler.close()
        for name, level in previous_levels.items():
            logging.getLogger(name).setLevel(level)
        configure_logging(logging.getLevelName(previous_root_level))
        root.setLevel(previous_root_level)

    assert PHONE not in stream.getvalue()


def test_json_formatter_redacts_extra_redaction_escape_hatch() -> None:
    """即使调用方忘了脱敏，Formatter 也会再兜一层。"""
    logger = get_logger("test")
    with captured_json_logs() as stream:
        logger.setLevel(logging.INFO)
        logger.info("x", extra={"extra_fields": {"payload": {"owner_phone": PHONE, "chipNo": CHIP}}})

    text = stream.getvalue()
    assert PHONE not in text and CHIP not in text
    assert json.loads(text)["payload"] == {"owner_phone": "***", "chipNo": "***"}


# ---------------------------------------------------------------------------
# 端到端：真实工具调用的日志里没有敏感值
# ---------------------------------------------------------------------------


async def test_tool_call_log_never_contains_raw_sensitive_values(make_client) -> None:
    client = make_client()
    server, _ = build_server(Settings(base_url="http://127.0.0.1:8080"), client)

    with captured_json_logs() as stream:
        async with Client(server) as mcp_client:
            result = await mcp_client.call_tool(
                "list_pets",
                {
                    "ownerPhone": PHONE,
                    "ownerName": "张三",
                    "species": "犬",
                    "page": 1,
                    "pageSize": 20,
                },
            )

    assert result.is_error is False

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    calls = [json.loads(line) for line in lines if json.loads(line).get("tool_name") == "list_pets"]
    assert len(calls) == 1

    record = calls[0]
    assert set(record) >= {"timestamp", "tool_name", "params", "status", "duration_ms"}
    assert record["status"] == "ok"
    assert record["duration_ms"] >= 0
    assert record["params"]["ownerPhone"] == "***"
    assert record["params"]["ownerName"] == "张三"

    for secret in (PHONE,):
        assert secret not in stream.getvalue()


async def test_failed_tool_call_is_logged_with_error_code(make_client) -> None:
    client = make_client()
    server, _ = build_server(Settings(base_url="http://127.0.0.1:8080"), client)

    with captured_json_logs() as stream:
        async with Client(server) as mcp_client:
            result = await mcp_client.call_tool("list_pets", {"pageSize": 999})

    assert result.is_error is True

    records = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    calls = [record for record in records if record.get("tool_name") == "list_pets"]
    assert len(calls) == 1
    assert calls[0]["status"] == "VALIDATION_ERROR"
