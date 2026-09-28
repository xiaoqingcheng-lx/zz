"""配置解析测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pet_hospital_mcp.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MCP_HOST,
    DEFAULT_MCP_PORT,
    Settings,
)


def test_defaults_match_teaching_contract() -> None:
    settings = Settings.from_env({})
    assert settings.base_url == "http://127.0.0.1:8080"
    assert settings.base_url == DEFAULT_BASE_URL
    assert settings.mcp_host == DEFAULT_MCP_HOST == "127.0.0.1"
    assert settings.mcp_port == DEFAULT_MCP_PORT == 8000
    assert settings.mcp_path == "/mcp"
    assert settings.is_loopback is True
    assert settings.endpoint_url == "http://127.0.0.1:8000/mcp"


def test_env_overrides() -> None:
    settings = Settings.from_env(
        {
            "PET_HOSPITAL_BASE_URL": "http://127.0.0.1:9090/",
            "MCP_HOST": "0.0.0.0",
            "MCP_PORT": "8123",
            "MCP_PATH": "mcp",
            "PET_HOSPITAL_TIMEOUT": "3.5",
            "PET_HOSPITAL_MAX_RETRIES": "5",
            "PET_HOSPITAL_TRUST_ENV": "true",
            "LOG_LEVEL": "debug",
        }
    )
    assert settings.base_url == "http://127.0.0.1:9090"  # 末尾斜杠被去掉
    assert settings.mcp_host == "0.0.0.0"
    assert settings.mcp_port == 8123
    assert settings.mcp_path == "/mcp"
    assert settings.request_timeout == 3.5
    assert settings.max_retries == 5
    assert settings.trust_env is True
    assert settings.log_level == "DEBUG"
    assert settings.is_loopback is False


def test_blank_env_values_fall_back_to_defaults() -> None:
    settings = Settings.from_env({"MCP_HOST": "   ", "MCP_PORT": ""})
    assert settings.mcp_host == DEFAULT_MCP_HOST
    assert settings.mcp_port == DEFAULT_MCP_PORT


@pytest.mark.parametrize(
    "env",
    [
        {"PET_HOSPITAL_BASE_URL": "127.0.0.1:8080"},  # 缺协议
        {"MCP_PORT": "not-a-number"},
        {"MCP_PORT": "70000"},  # 超出端口范围
        {"PET_HOSPITAL_TIMEOUT": "0"},  # 超时必须为正
        {"PET_HOSPITAL_MAX_RETRIES": "-1"},
    ],
)
def test_invalid_env_is_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings.from_env(env)
