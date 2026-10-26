# -*- coding: utf-8 -*-
"""xAgent —— 能调用本地 CLI 工具的大模型 Agent（Function Calling 完整闭环）。

流程（Agent 调用本地工具的完整过程）：
    1. 把「工具声明」（RunCli 的 JSON Schema）随消息发给 LLM；
    2. LLM 若决定用工具 → 返回 tool_calls（工具名 + JSON 参数）；
    3. Agent 本地执行工具，把结果以 role=tool 消息回传；
    4. LLM 结合结果继续推理——可能再次调工具，也可能给出最终回答；
    5. 循环直到出现最终回答，或达到 MAX_ROUNDS 上限（防止死循环）。

凭据复用 agent 根目录的 config.ini / _secret.py（经 llm_cli._load_config）。
"""
import json
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent        # agent/ 根目录
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_cli                                        # noqa: E402  复用凭据加载
from run_cli_tool import TOOL_SCHEMA, execute_tool    # noqa: E402

BASE_URL, _KEY, MODEL = llm_cli._load_config()
TIMEOUT = 120          # 单次 LLM 请求超时（秒）
MAX_ROUNDS = 6         # 最多「工具调用→结果回传」轮数，防死循环

SYSTEM_PROMPT = (
    "你是 xAgent，一个可以调用本地命令行工具的智能助手。"
    "需要了解本机信息或执行操作时，主动使用 RunCli 工具获取真实数据，"
    "基于工具返回的真实结果回答，不要凭空编造。"
    "回答使用简体中文，简洁清晰。"
)


def _chat(messages: list) -> dict:
    """调用 chat/completions（非流式），返回 choices[0].message。"""
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": [TOOL_SCHEMA],          # 把 RunCli 声明给 LLM
        "tool_choice": "auto",           # 由 LLM 自行决定是否调用
    }
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + _KEY,
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]


def run_agent(prompt: str, history: list = (), verbose: bool = True) -> tuple[str, list]:
    """跑一次完整的 Agent 推理。

    返回 (最终回答, 更新后的 history)。verbose=True 时在控制台
    打印每一步「LLM 决策 → 本地执行 → 结果回传」，便于观察全过程。
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += list(history)
    messages.append({"role": "user", "content": prompt})

    for _round in range(1, MAX_ROUNDS + 1):
        msg = _chat(messages)

        # ---- 情形一：LLM 决定调用工具 ----
        if msg.get("tool_calls"):
            messages.append(msg)         # 先记录助手的 tool_calls 决策
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"] or "{}")
                if verbose:
                    print(f"  🔧 Agent 决定调用工具：{name}({args})")

                result = execute_tool(name, args)          # 本地执行
                if verbose:
                    preview = result if len(result) <= 200 else result[:200] + "…"
                    print(f"  📤 执行结果回传：{preview}")

                messages.append({        # 结果以 role=tool 回传给 LLM
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
            continue                     # 带着 Tool 结果再问 LLM

        # ---- 情形二：LLM 给出最终回答 ----
        answer = msg.get("content") or ""
        history = list(history) + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ]
        return answer, history

    return "（达到最大工具调用轮数上限，已停止）", list(history)
