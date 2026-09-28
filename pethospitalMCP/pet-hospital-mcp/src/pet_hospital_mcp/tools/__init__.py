"""工具包。

新增工具的步骤（不需要改其它任何地方）：

1. 在本目录新建 ``<tool_name>.py``；
2. 定义 ``TOOL_NAME``、``TOOL_DESCRIPTION``、严格输入模型 ``INPUT_MODEL``；
3. 实现 ``register(server, client)``，内部用 ``@server.tool(name=TOOL_NAME, ...)`` 注册。

本模块会自动发现同目录下的所有模块，把 ``INPUT_MODEL`` 交给契约中间件做严格校验，
并调用每个模块的 ``register``。
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Any

from pydantic import BaseModel

from ..logging_config import get_logger
from ..rest_client import PetHospitalClient

__all__ = ["discover_tool_modules", "input_models", "register_tools"]

logger = get_logger("tools")

_DISCOVERED: dict[str, ModuleType] | None = None


def discover_tool_modules() -> dict[str, ModuleType]:
    """导入并缓存 ``tools`` 包下的全部工具模块（忽略下划线开头的）。"""
    global _DISCOVERED
    if _DISCOVERED is None:
        modules: dict[str, ModuleType] = {}
        for info in pkgutil.iter_modules(__path__):
            if info.name.startswith("_"):
                continue
            modules[info.name] = importlib.import_module(f"{__name__}.{info.name}")
        _DISCOVERED = modules
    return _DISCOVERED


def input_models() -> dict[str, type[BaseModel]]:
    """``{工具名: 严格输入模型}``，交给契约中间件。"""
    registry: dict[str, type[BaseModel]] = {}
    for module_name, module in discover_tool_modules().items():
        tool_name = getattr(module, "TOOL_NAME", None)
        model = getattr(module, "INPUT_MODEL", None)
        if isinstance(tool_name, str) and isinstance(model, type) and issubclass(model, BaseModel):
            registry[tool_name] = model
        else:
            logger.debug("skipping module without TOOL_NAME/INPUT_MODEL", extra={"extra_fields": {"module": module_name}})
    return registry


def register_tools(server: Any, client: PetHospitalClient) -> list[str]:
    """把所有已发现的工具注册到 ``server``，返回已注册的工具名列表。"""
    registered: list[str] = []
    for module_name, module in discover_tool_modules().items():
        register = getattr(module, "register", None)
        if not callable(register):
            continue
        register(server, client)
        registered.append(str(getattr(module, "TOOL_NAME", module_name)))
    logger.info("tools registered", extra={"extra_fields": {"tools": registered}})
    return registered
