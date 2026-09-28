"""pytest 夹具。

硬性约束：**测试期间绝不访问真实 Go 服务**。
所有上游调用都走 :class:`httpx.MockTransport`；HTTP 端到端测试只连本机临时端口。
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
import time
from typing import Any, Callable, Iterator

# 开发机/CI 可能设置了 HTTP_PROXY，会把回环请求劫持到代理上。测试只走回环，先关掉。
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import httpx  # noqa: E402
import pytest  # noqa: E402

from pet_hospital_mcp.config import Settings  # noqa: E402
from pet_hospital_mcp.logging_config import configure_logging  # noqa: E402
from pet_hospital_mcp.rest_client import PetHospitalClient  # noqa: E402
from pet_hospital_mcp.server import build_server  # noqa: E402
from tests.helpers import BASE_URL, HttpMCP, UpstreamRecorder  # noqa: E402

# 测试期间静音日志（同时让 MCPServer 内部的 logging.basicConfig 变成空操作）。
configure_logging("CRITICAL")


@pytest.fixture
def recorder() -> UpstreamRecorder:
    return UpstreamRecorder()


@pytest.fixture
def make_client(recorder: UpstreamRecorder) -> Callable[..., PetHospitalClient]:
    """构造只走 MockTransport 的客户端；重试退避置 0 以保证测试快速。"""

    def _make(**overrides: Any) -> PetHospitalClient:
        options: dict[str, Any] = {
            "timeout": 5.0,
            "max_retries": 0,
            "trust_env": False,
            "transport": httpx.MockTransport(recorder.handler),
            "backoff_seconds": 0.0,
        }
        options.update(overrides)
        return PetHospitalClient(BASE_URL, **options)

    return _make


@pytest.fixture
def settings() -> Settings:
    return Settings(base_url=BASE_URL, mcp_host="127.0.0.1", mcp_port=9999)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _serve(client: PetHospitalClient) -> Iterator[HttpMCP]:
    """在后台线程里跑一个真实的 uvicorn，把 MCP HTTP 端点暴露在随机本机端口上。"""
    import uvicorn

    port = _free_port()
    settings = Settings(base_url=BASE_URL, mcp_host="127.0.0.1", mcp_port=port)
    server, tools = build_server(settings, client)

    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="127.0.0.1",
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not getattr(uvicorn_server, "started", False):
        if not thread.is_alive():  # pragma: no cover - 启动失败
            raise RuntimeError("uvicorn failed to start")
        time.sleep(0.05)
    if not getattr(uvicorn_server, "started", False):  # pragma: no cover - 启动超时
        raise RuntimeError("uvicorn did not start in time")

    harness = HttpMCP(f"http://127.0.0.1:{port}", list(tools))
    try:
        yield harness
    finally:
        harness.close()
        uvicorn_server.should_exit = True
        thread.join(timeout=15)


@pytest.fixture
def http_mcp(make_client: Callable[..., PetHospitalClient]) -> Iterator[HttpMCP]:
    """无状态 Streamable HTTP 端点（上游不重试，便于对每个失败精确断言）。"""
    with _serve(make_client(max_retries=0)) as harness:
        yield harness


@pytest.fixture
def http_mcp_retrying(make_client: Callable[..., PetHospitalClient]) -> Iterator[HttpMCP]:
    """同上，但上游客户端带 2 次重试，用于验证有限重试在 HTTP 链路上生效。"""
    with _serve(make_client(max_retries=2, backoff_seconds=0.0)) as harness:
        yield harness
