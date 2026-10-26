# -*- coding: utf-8 -*-
"""RunCli —— xAgent 的 Function Calling 工具：调用本地已安装的任意命令行程序。

设计要点（对应实验要求）：
1. 程序名 + 参数**拼装为列表**，subprocess 以 ``shell=False`` 执行，
   不拼接 Shell 命令字符串，避免注入/转义问题；
2. 返回 stdout、stderr、退出码，供 LLM 判断执行结果并决定下一步；
3. 设定执行超时，超时后终止进程并把超时信息作为结果返回；
4. 过长输出按 MAX_CHARS 截断，并**标明截断情况**，避免撑爆上下文；
5. 教学阶段暂不做白名单/黑名单/审批机制，命令以运行 xAgent
   的当前用户权限执行，仅用于受控教学实验环境。
"""
import json
import subprocess

# ---------- 可按需调整的执行参数 ----------
TIMEOUT = 30        # 单条命令超时（秒）
MAX_CHARS = 4000    # stdout / stderr 各自的最大返回字符数


# ---------- Function Calling 工具声明（发给 LLM 的 JSON Schema） ----------
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "RunCli",
        "description": (
            "在本地执行一个命令行程序并返回结果。"
            "command 是程序名称（如 python、git、ipconfig）；"
            "args 是字符串参数列表，可为空数组。"
            "Windows 内置命令（dir、type、echo 等）不是独立程序，"
            "需要经 cmd 调用，例如 command='cmd'、args=['/c', 'dir']。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要运行的程序名称",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "传给程序的参数列表，没有参数就传 []",
                },
            },
            "required": ["command"],
        },
    },
}


def _truncate(text: str, label: str) -> str:
    """超长文本截断，并明确标注截断情况。"""
    if text and len(text) > MAX_CHARS:
        return (
            text[:MAX_CHARS]
            + f"\n...[{label}过长已截断：原始 {len(text)} 字符，仅保留前 {MAX_CHARS} 字符]"
        )
    return text


def run_cli(command: str, args=None) -> tuple[str, str, int]:
    """执行命令，返回 (stdout, stderr, exit_code)。

    shell=False：直接按列表启动进程，不经 shell 解释。
    任何执行异常都不抛出——统一转换成结果文本，让 LLM 能读到失败原因。
    """
    args = [str(a) for a in (args or [])]
    cmd_list = [command] + args                      # 列表拼装，不拼字符串
    try:
        proc = subprocess.run(
            cmd_list,
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",                        # 防止 GBK/UTF-8 混编打崩
            timeout=TIMEOUT,
        )
        stdout = _truncate(proc.stdout, "stdout")
        stderr = _truncate(proc.stderr, "stderr")
        return stdout, stderr, proc.returncode
    except FileNotFoundError:
        return "", f"找不到程序 {command!r}（未安装或不在 PATH 中）", -1
    except subprocess.TimeoutExpired:
        return "", f"命令执行超过 {TIMEOUT} 秒，已被强制终止", -2
    except OSError as e:
        return "", f"启动进程失败：{e}", -3


def execute_tool(name: str, arguments: dict) -> str:
    """Function Calling 的统一入口：校验工具名 → 执行 → 序列化结果。

    返回值是一个 JSON 字符串，作为 tool 消息回传给 LLM。
    """
    if name != "RunCli":
        return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)

    command = str(arguments.get("command", "")).strip()
    args = arguments.get("args") or []
    if not command:
        return json.dumps({"error": "缺少必填参数 command"}, ensure_ascii=False)

    stdout, stderr, exit_code = run_cli(command, args)
    return json.dumps(
        {
            "command": command,
            "args": [str(a) for a in args],
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        },
        ensure_ascii=False,
    )
