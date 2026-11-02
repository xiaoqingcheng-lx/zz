# -*- coding: utf-8 -*-
"""xAgent —— 能调用本地 CLI、读写文件、创建/加载技能（Skill）的大模型 Agent。

工具链路（Function Calling 完整闭环）：
    A. 执行命令（RunCli）：LLM 返回 tool_calls → 本地执行 → role=tool 回传 → 继续推理；
    B. 技能加载（loadSkill，Agent Skills 规范）：
       1. **初始化**：以工作目录为项目根，扫描 ``.agents/skills/``，
          只解析每个 SKILL.md 的 name/description（不读正文）；
       2. **注入**：把技能清单渲染进 System Prompt，告诉 LLM 有哪些技能可用；
       3. **按需加载**：LLM 认为需要时调用 loadSkill，正文此时才进入上下文，
          技能引用的附加文件可用 filename 参数二次加载。
    C. 技能创建（createSkill）：按自然语言要求在 ``.agents/skills/`` 下建英文子目录
       并写 SKILL.md（校验 Frontmatter、拒绝覆盖），创建后自动热加载；
    D. 文件操作（fileOps）：在技能目录内建 references/、scripts/ 等目录或写辅助文件；
    E. 文档处理（officeCli）：调用 officecli 读写 .docx/.xlsx/.pptx，可执行文件自动定位。
    循环直到出现最终回答，或达到 MAX_ROUNDS 上限（防止死循环）。

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
from run_cli_tool import TOOL_SCHEMA as RUNCLI_SCHEMA, execute_tool as run_cli_execute  # noqa: E402
from load_skill_tool import TOOL_SCHEMA as LOADSKILL_SCHEMA, execute_tool as load_skill_execute  # noqa: E402
from create_skill_tool import TOOL_SCHEMA as CREATESKILL_SCHEMA, execute_tool as create_skill_execute  # noqa: E402
from file_ops_tool import TOOL_SCHEMA as FILEOPS_SCHEMA, execute_tool as file_ops_execute  # noqa: E402
from office_cli_tool import TOOL_SCHEMA as OFFICECLI_SCHEMA, execute_tool as office_cli_execute  # noqa: E402
from skills import SkillRegistry, _loose_key         # noqa: E402  Skill 发现与注册

BASE_URL, _KEY, MODEL = llm_cli._load_config()
TIMEOUT = 120          # 单次 LLM 请求超时（秒）
MAX_ROUNDS = 10        # 最多「工具调用→结果回传」轮数，防死循环（createSkill+fileOps 需多轮）

# --------------------------------------------------------------------------- #
# 初始化阶段：技能发现与注册（只读 name/description，不读正文）
# --------------------------------------------------------------------------- #
SKILLS = SkillRegistry.discover()

BASE_PROMPT = (
    "你是 xAgent，一个可以调用本地工具的智能助手。"
    "你只能调用这五个工具：RunCli、loadSkill、createSkill、fileOps、officeCli。"
    "注意：技能（Skill）本身不是工具，技能名不能当工具名调用；"
    "想使用某个技能时，必须调用 loadSkill 工具，把技能名填进 name 参数。"
    "需要了解本机信息或执行操作时，主动使用 RunCli 工具获取真实数据，"
    "基于工具返回的真实结果回答，不要凭空编造。"
    "下面列出的技能（Skill）是工作规范：当用户请求属于某个技能的适用范围时，"
    "必须先调用 loadSkill 加载它的完整说明，再严格按说明执行；"
    "技能中引用的附加资料，可用 loadSkill 的 filename 参数按需读取。"
    "当用户要求新建一个技能时，调用 createSkill 工具（name 用英文小写加连字符，"
    "skillContext 写完整的 SKILL.md：Frontmatter 含 name、description，后接正文规则）；"
    "如果新技能还需要 references/、scripts/ 等目录或辅助文件，创建成功后继续调用 fileOps 工具完成。"
    "涉及 Word、Excel、PPT 文档的任何操作，第一个动作固定是 loadSkill({'name': 'officecli'})，"
    "读到使用说明后再调用 officeCli 工具执行命令；不要跳过这一步直接调 officeCli，"
    "也不要安装或依赖 Office。"
    "回答使用简体中文，简洁清晰。"
)


def system_prompt() -> str:
    """实时拼装 System Prompt（含技能清单）。

    每次请求都重新渲染，这样刚用 createSkill 建好的技能能立刻出现在清单里。
    """
    section = SKILLS.prompt_section()
    return BASE_PROMPT + ("\n\n" + section if section else "")


# 兼容旧接口：模块导入时的快照（交互提示等场景可用）
SYSTEM_PROMPT = system_prompt()

# 本轮可用的全部工具声明：RunCli + loadSkill + createSkill + fileOps + officeCli
TOOL_SCHEMAS = [RUNCLI_SCHEMA, LOADSKILL_SCHEMA, CREATESKILL_SCHEMA, FILEOPS_SCHEMA, OFFICECLI_SCHEMA]


def _chat(messages: list) -> dict:
    """调用 chat/completions（非流式），返回 choices[0].message。"""
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOL_SCHEMAS,           # 把 RunCli / loadSkill 声明给 LLM
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


def _sanitize_message(msg: dict) -> dict:
    """只保留回传 LLM 需要的字段。

    模型原始返回里可能带 reasoning_content 等附加字段，
    原样发回有可能触发 400 参数错误，这里做一次净化。
    """
    clean = {"role": msg.get("role", "assistant")}
    if msg.get("content") is not None:
        clean["content"] = msg["content"]
    if msg.get("tool_calls"):
        clean["tool_calls"] = msg["tool_calls"]
    return clean


# 本次会话已加载过正文的技能（宽松键），用于「没加载说明就动手」的兜底拦截
_LOADED_SKILLS: set[str] = set()


def _mark_loaded(name: str) -> None:
    if name:
        _LOADED_SKILLS.add(_loose_key(name))


def dispatch_tool(name: str, arguments: dict) -> str:
    """工具分发：按工具名路由到具体实现（新增工具只改这里）。"""
    if name == "RunCli":
        return run_cli_execute(name, arguments)
    if name == "loadSkill":
        raw = load_skill_execute(SKILLS, arguments)
        try:
            _mark_loaded(json.loads(raw).get("skill", ""))
        except (ValueError, AttributeError):
            pass
        return raw
    if name == "createSkill":
        raw = create_skill_execute(SKILLS, arguments)
        try:
            payload = json.loads(raw)
            if payload.get("ok"):
                _mark_loaded(payload.get("skill", ""))
        except (ValueError, AttributeError):
            pass
        return raw
    if name == "fileOps":
        return file_ops_execute(SKILLS.root, arguments)
    if name == "officeCli":
        # 兜底：没读过 officecli 说明就操作文档，很容易踩坑，先让它加载
        if SKILLS.get("officecli") and _loose_key("officecli") not in _LOADED_SKILLS:
            return json.dumps({
                "error": "尚未加载 officecli 技能说明，已拒绝执行",
                "hint": "先调用 loadSkill({'name': 'officecli'}) 读取使用规则，再调用本工具",
            }, ensure_ascii=False)
        # 搜索根：技能目录 + 其上一级（课程要求把 exe 放在 office 目录下）
        return office_cli_execute(arguments, [SKILLS.root, SKILLS.root.parent])
    # 兜底：模型把技能名当成工具名调用时，自动转成「加载该技能」，避免整轮失败
    skill = SKILLS.get(name)
    if skill is not None:
        payload = json.loads(load_skill_execute(SKILLS, {"name": skill.name}))
        _mark_loaded(skill.name)
        payload["note"] = (
            f"「{skill.name}」是技能（Skill）而不是工具，本次已自动加载它的说明；"
            "请按说明执行，后续请用 loadSkill 工具调用技能。"
        )
        return json.dumps(payload, ensure_ascii=False)
    return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)


def run_agent(prompt: str, history: list = (), verbose: bool = True) -> tuple[str, list]:
    """跑一次完整的 Agent 推理。

    返回 (最终回答, 更新后的 history)。verbose=True 时在控制台
    打印每一步「LLM 决策 → 本地执行 → 结果回传」，便于观察全过程。
    """
    messages = [{"role": "system", "content": system_prompt()}]
    messages += list(history)
    messages.append({"role": "user", "content": prompt})

    for _round in range(1, MAX_ROUNDS + 1):
        messages[0]["content"] = system_prompt()   # 技能清单可能在上一轮被 createSkill 改变
        try:
            msg = _chat(messages)
        except Exception as e:               # 网络/超时/API 错误：给用户明确反馈
            answer = f"[出错] 请求失败：{e}"
            return answer, list(history)

        # ---- 情形一：LLM 决定调用工具 ----
        if msg.get("tool_calls"):
            messages.append(_sanitize_message(msg))   # 先记录助手的决策
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"] or "{}")
                if verbose:
                    print(f"  🔧 Agent 决定调用工具：{name}({args})")

                result = dispatch_tool(name, args)          # 本地执行
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
