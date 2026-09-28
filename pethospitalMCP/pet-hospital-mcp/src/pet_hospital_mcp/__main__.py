"""启动入口：``python -m pet_hospital_mcp`` 或 ``pet-hospital-mcp``。"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from pydantic import ValidationError

from .config import Settings
from .logging_config import configure_logging, get_logger
from .rest_client import PetHospitalClient
from .server import SERVER_NAME, SERVER_VERSION, build_server, sdk_version

logger = get_logger("main")

# 仅在非本机监听时才放开 SDK 的 Host/Origin 白名单；本机监听保持 SDK 默认（只接受 localhost）。
_LOOPBACK_HINT = "仅监听本机。如需其他机器访问，请显式设置 MCP_HOST，并自行确认网络边界。"


def _transport_security(settings: Settings):
    """按监听地址决定 SDK 传输层安全设置（本项目不做认证/CORS/Origin 校验）。"""
    from mcp.server.transport_security import TransportSecuritySettings

    if settings.is_loopback:
        return None
    logger.warning(
        "binding to a non-loopback host; DNS-rebinding allowlist disabled",
        extra={"extra_fields": {"mcp_host": settings.mcp_host}},
    )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _banner(settings: Settings, tools: list[str]) -> str:
    return "\n".join(
        [
            "",
            f"  {SERVER_NAME} v{SERVER_VERSION}  (MCP 2026-07-28 · 官方 Python SDK {sdk_version()})",
            f"    上游 Go REST API : {settings.base_url}",
            f"    MCP 端点         : {settings.endpoint_url}",
            f"    健康检查         : http://{settings.mcp_host}:{settings.mcp_port}/health",
            f"    工具             : {', '.join(tools) or '(none)'}",
            f"    传输             : Streamable HTTP，无状态（无会话、无 Mcp-Session-Id）",
            f"    说明             : {_LOOPBACK_HINT}",
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pet-hospital-mcp",
        description="把 Go 宠物医院 REST API 暴露为 MCP 服务（无状态 Streamable HTTP）。",
    )
    parser.add_argument("--version", action="version", version=f"{SERVER_NAME} {SERVER_VERSION}")
    parser.parse_args(argv)

    # 先装日志，再构造 MCPServer：MCPServer 会调用 logging.basicConfig()，
    # 根 logger 已有 handler 时它才会跳过，这样我们的 JSON 日志才是唯一出口。
    configure_logging(_level_from_env())

    try:
        settings = Settings.from_env()
    except ValidationError as exc:
        for err in exc.errors(include_url=False, include_input=False):
            field = ".".join(str(part) for part in err.get("loc", ()))
            print(f"配置错误：{field} {err.get('msg')}", file=sys.stderr)
        return 2

    if settings.log_level != _level_from_env():
        configure_logging(settings.log_level)

    import uvicorn

    client = PetHospitalClient(
        settings.base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        trust_env=settings.trust_env,
    )
    server, tools = build_server(settings, client)
    app = server.streamable_http_app(
        streamable_http_path=settings.mcp_path,
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(settings),
        host=settings.mcp_host,
    )

    print(_banner(settings, tools), file=sys.stderr, flush=True)
    try:
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port, log_level=settings.log_level.lower())
    finally:
        import anyio

        anyio.run(client.aclose)
    return 0


def _level_from_env() -> str:
    import os

    return (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
