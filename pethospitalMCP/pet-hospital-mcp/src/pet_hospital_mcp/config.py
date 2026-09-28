"""运行配置。

全部来自环境变量，默认值与实训要求一致：

====================== ========================================== ==========================
环境变量                含义                                        默认值
====================== ========================================== ==========================
``PET_HOSPITAL_BASE_URL`` 上游 Go 宠物医院 REST API 基地址          ``http://127.0.0.1:8080``
``MCP_HOST``            MCP 服务监听地址（默认仅本机）              ``127.0.0.1``
``MCP_PORT``            MCP 服务监听端口                            ``8000``
``MCP_PATH``            MCP 端点路径                               ``/mcp``
``PET_HOSPITAL_TIMEOUT`` 单次上游请求超时（秒）                      ``10``
``PET_HOSPITAL_MAX_RETRIES`` 上游失败后的额外重试次数（有限重试）     ``2``
``PET_HOSPITAL_TRUST_ENV`` 是否信任 ``HTTP_PROXY`` 等环境变量        ``false``
``LOG_LEVEL``           日志级别                                   ``INFO``
====================== ========================================== ==========================
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["DEFAULT_BASE_URL", "DEFAULT_MCP_HOST", "DEFAULT_MCP_PORT", "Settings"]

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000
DEFAULT_MCP_PATH = "/mcp"


class Settings(BaseModel):
    """进程级配置。构造后不可变。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    base_url: str = Field(default=DEFAULT_BASE_URL, description="上游 Go REST API 基地址。")
    mcp_host: str = Field(default=DEFAULT_MCP_HOST, description="MCP 服务监听地址。")
    mcp_port: int = Field(default=DEFAULT_MCP_PORT, ge=1, le=65535, description="MCP 服务监听端口。")
    mcp_path: str = Field(default=DEFAULT_MCP_PATH, description="MCP HTTP 端点路径。")
    request_timeout: float = Field(default=10.0, gt=0, description="单次上游请求超时（秒）。")
    max_retries: int = Field(default=2, ge=0, le=10, description="上游失败后的额外重试次数。")
    trust_env: bool = Field(
        default=False,
        description="是否让 httpx 读取 HTTP_PROXY/NO_PROXY 等环境变量。"
        "默认关闭：上游是本机地址，跟随系统代理只会带来难以排查的失败。",
    )
    log_level: str = Field(default="INFO", description="日志级别。")

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        url = value.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("PET_HOSPITAL_BASE_URL 必须以 http:// 或 https:// 开头")
        return url

    @field_validator("mcp_path")
    @classmethod
    def _normalize_path(cls, value: str) -> str:
        path = value.strip()
        if not path:
            return DEFAULT_MCP_PATH
        return path if path.startswith("/") else f"/{path}"

    @field_validator("log_level")
    @classmethod
    def _normalize_level(cls, value: str) -> str:
        return value.strip().upper()

    @property
    def endpoint_url(self) -> str:
        """供客户端连接的完整 MCP 端点 URL。"""
        return f"http://{self.mcp_host}:{self.mcp_port}{self.mcp_path}"

    @property
    def is_loopback(self) -> bool:
        return self.mcp_host in {"127.0.0.1", "::1", "localhost"}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """从环境变量读取配置；``env`` 便于测试注入。"""
        source = os.environ if env is None else env

        def raw(name: str, default: Any = None) -> Any:
            value = source.get(name)
            if value is None or not str(value).strip():
                return default
            return value

        return cls(
            base_url=raw("PET_HOSPITAL_BASE_URL", DEFAULT_BASE_URL),
            mcp_host=raw("MCP_HOST", DEFAULT_MCP_HOST),
            mcp_port=raw("MCP_PORT", DEFAULT_MCP_PORT),
            mcp_path=raw("MCP_PATH", DEFAULT_MCP_PATH),
            request_timeout=raw("PET_HOSPITAL_TIMEOUT", 10.0),
            max_retries=raw("PET_HOSPITAL_MAX_RETRIES", 2),
            trust_env=str(raw("PET_HOSPITAL_TRUST_ENV", "false")).strip().lower() in {"1", "true", "yes", "on"},
            log_level=raw("LOG_LEVEL", "INFO"),
        )
