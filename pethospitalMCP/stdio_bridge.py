# -*- coding: utf-8 -*-
"""PeiHospitalMCP 的 stdio 桥：供 AnythingLLM 桌面版等只支持 stdio 的 MCP 客户端使用。

原理：复用 pet-hospital-mcp 已装配好的 MCPServer（工具、中间件全部一致），
只把传输层从 Streamable HTTP 换成 stdio（标准输入/输出上的 JSON-RPC）。

用法（一般不需要手动跑）：
    set PET_HOSPITAL_BASE_URL=http://127.0.0.1:8080
    .venv-mcp\\Scripts\\python.exe stdio_bridge.py
"""
from __future__ import annotations

import anyio

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.logging_config import configure_logging
from pet_hospital_mcp.rest_client import PetHospitalClient
from pet_hospital_mcp.server import build_server


async def main() -> None:
    # stdio 被协议占用，日志只能走 stderr
    configure_logging("warning")
    settings = Settings.from_env()
    client = PetHospitalClient(
        settings.base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        trust_env=settings.trust_env,
    )
    server, _tools = build_server(settings, client)
    try:
        await server.run_stdio_async()
    finally:
        await client.aclose()


if __name__ == "__main__":
    anyio.run(main)
