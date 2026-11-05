# -*- coding: utf-8 -*-
"""app_config —— xAgent 的统一配置入口（config.ini + 内置默认值）。

设计：
    · 查找顺序：当前工作目录 config.ini → xagent 代码目录 config.ini；
      两处都没有 → 在当前目录生成一份带注释的完整 mock config.ini，
      并由调用方弹提示让用户修改后重启（ensure_config / MOCK_NOTICE）。
    · 所有参数都有内置默认值：config.ini 里没写的字段自动回落默认值，
      不会因为少写一行而崩掉。
    · 模块级 CFG = load()，xagent / TUI / CLI 统一从这里拿参数。

config.ini 分节：
    [llm]      base_url / api_key / model
    [agent]    timeout / max_rounds / summary_tokens
    [context]  warn_ratio / default_window
    [mcp]      connect_timeout / call_timeout
    [sessions] dir / autosave
"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "config.ini"

# --------------------------------------------------------------------------- #
# 内置默认值（config.ini 没写就回落到这里）
# --------------------------------------------------------------------------- #
DEFAULTS = {
    "llm": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",                       # 留空回落 _secret.py 内置凭据
        "model": "qwen-plus",
    },
    "agent": {
        "timeout": "120",                    # 单次 LLM 请求超时（秒）
        "max_rounds": "10",                  # 工具调用最大轮数
        "summary_tokens": "6000",            # 压缩摘要 max_tokens
    },
    "context": {
        "warn_ratio": "0.70",                # 上下文占用告警阈值
        "default_window": "128000",          # 查不到模型窗口时的兜底值
    },
    "mcp": {
        "connect_timeout": "8",              # MCP initialize/tools/list 超时
        "call_timeout": "30",                # MCP tools/call 超时
    },
    "sessions": {
        "dir": ".agents/sessions",           # 会话存档目录（相对项目根）
        "autosave": "1",                     # 每轮结束自动保存 1/0
    },
}

MOCK_API_KEY = "sk-请把这里替换成你自己的APIKey"

# 生成的 mock 配置：全字段 + 注释，用户改完保存重启即可
MOCK_TEMPLATE = """# xAgent 配置文件（首次运行自动生成）
# ⚠️ 当前是示例值：请至少把 [llm] api_key 改成你自己的，
#    修改保存后重新启动 xAgent 才能正常工作。

[llm]
# OpenAI 兼容接口地址（示例为阿里云百炼 DashScope）
base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
# 你的 API Key（必改）
api_key = {mock_key}
# 模型名（qwen-plus / qwen-max / qwen-turbo ...）
model = qwen-plus

[agent]
# 单次 LLM 请求超时（秒）
timeout = 120
# 一次提问最多「工具调用→结果回传」轮数
max_rounds = 10
# 上下文压缩摘要的 max_tokens
summary_tokens = 6000

[context]
# 上下文占用告警阈值（0~1，达到后暂停普通输入，只接受 /compact）
warn_ratio = 0.70
# 识别不出模型窗口时的兜底窗口大小（Tokens）
default_window = 128000

[mcp]
# MCP 服务器连接超时（秒）
connect_timeout = 8
# MCP 工具调用超时（秒）
call_timeout = 30

[sessions]
# 会话存档目录（相对项目根）
dir = .agents/sessions
# 每轮对话结束是否自动保存会话（1/0）
autosave = 1
"""

MOCK_NOTICE = (
    "⚠️ 未找到 config.ini，已在当前目录生成一份示例配置：\n"
    "    {path}\n"
    "请打开它，至少把 [llm] api_key 改成你自己的 API Key，\n"
    "保存后重新启动 xAgent 才能正常工作。"
)


@dataclass
class AppConfig:
    """解析后的全部配置项（都有值，调用方无需再判空）。"""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 120
    max_rounds: int = 10
    summary_tokens: int = 6000
    warn_ratio: float = 0.70
    default_window: int = 128_000
    mcp_connect_timeout: float = 8.0
    mcp_call_timeout: float = 30.0
    sessions_dir: str = ".agents/sessions"
    autosave: bool = True
    config_path: Path | None = None        # 实际生效的 config.ini 路径
    is_mock: bool = False                  # True = 刚生成的示例配置

    @property
    def api_key_missing(self) -> bool:
        key = (self.api_key or "").strip()
        return (not key) or key.startswith("sk-请把")


# --------------------------------------------------------------------------- #
# 查找 / 生成 / 解析
# --------------------------------------------------------------------------- #
def candidate_paths(cwd: Path | None = None) -> list[Path]:
    """config.ini 的候选位置：当前目录 → agent 根目录 → xagent 代码目录。"""
    here = Path(cwd or os.getcwd()).resolve()
    code_dir = Path(__file__).resolve().parent
    paths = [here / CONFIG_NAME]
    parent = code_dir.parent
    if parent != here:
        paths.append(parent / CONFIG_NAME)
    if code_dir not in (here, parent):
        paths.append(code_dir / CONFIG_NAME)
    return paths


def existing_config(cwd: Path | None = None) -> Path | None:
    """返回第一个真实存在的 config.ini，没有则 None。"""
    for p in candidate_paths(cwd):
        if p.is_file():
            return p
    return None


def ensure_config(cwd: Path | None = None) -> tuple[Path, bool]:
    """保证有 config.ini 可用：没有就生成 mock，返回 (路径, 是否新建)。"""
    found = existing_config(cwd)
    if found:
        return found, False
    target = (Path(cwd) if cwd else Path(os.getcwd())).resolve() / CONFIG_NAME
    target.write_text(MOCK_TEMPLATE.format(mock_key=MOCK_API_KEY), encoding="utf-8")
    return target, True


def _to_int(v: str, default: int) -> int:
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return default


def _to_float(v: str, default: float) -> float:
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return default


def _to_bool(v: str, default: bool) -> bool:
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "开"):
        return True
    if s in ("0", "false", "no", "off", "关"):
        return False
    return default


def load(cwd: Path | None = None) -> AppConfig:
    """解析 config.ini（没有就用全默认值），返回 AppConfig。"""
    cfg = configparser.ConfigParser()
    path = existing_config(cwd)
    is_mock = False
    if path:
        cfg.read(path, encoding="utf-8")
    else:
        cfg.read_dict(DEFAULTS)
        is_mock = True                        # 没有任何配置文件：默认值兜底

    def get(section: str, key: str) -> str:
        return cfg.get(section, key, fallback=DEFAULTS[section][key]).strip()

    key = get("llm", "api_key")
    if (not key) or key.startswith("sk-请把"):
        # 空着或还是示例占位符：尝试内置凭据（打包分发场景），失败保持为空
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from _secret import key as builtin      # type: ignore
            key = builtin().strip()
        except Exception:
            key = key if key else ""
    return AppConfig(
        base_url=get("llm", "base_url") or DEFAULTS["llm"]["base_url"],
        api_key=key,
        model=get("llm", "model") or DEFAULTS["llm"]["model"],
        timeout=_to_int(get("agent", "timeout"), 120),
        max_rounds=_to_int(get("agent", "max_rounds"), 10),
        summary_tokens=_to_int(get("agent", "summary_tokens"), 6000),
        warn_ratio=min(max(_to_float(get("context", "warn_ratio"), 0.70), 0.05), 0.95),
        default_window=_to_int(get("context", "default_window"), 128_000),
        mcp_connect_timeout=_to_float(get("mcp", "connect_timeout"), 8.0),
        mcp_call_timeout=_to_float(get("mcp", "call_timeout"), 30.0),
        sessions_dir=get("sessions", "dir") or ".agents/sessions",
        autosave=_to_bool(get("sessions", "autosave"), True),
        config_path=path,
        is_mock=is_mock,
    )


CFG = load()          # 模块级默认实例（启动时调用 ensure_config 后可再 load 一次）
