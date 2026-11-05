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

配置与状态（全部来自 config.ini + 内置默认值，见 app_config.py）：
    · [llm] / [agent] / [context] / [mcp] / [sessions] 五节，缺项自动回落默认值；
    · 首次运行若无 config.ini，入口会生成带注释的 mock 文件并提示修改后重启。

MCP 异步加载：
    · 模块导入时只建空注册表，不连接；TUI 先出界面，再在后台线程连接，
      完成后回调刷新边栏；CLI 用 load_mcp_blocking() 同步加载。

会话与 AGENTS.md（见 session_store.py）：
    · /new /resume /save 会话存档在 .agents/sessions/；
    · 新会话若项目根有 AGENTS.md，注入为第一条消息并随会话持久化（一次注入，全程复用）。
"""
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent        # agent/ 根目录
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_cli_tool import TOOL_SCHEMA as RUNCLI_SCHEMA, execute_tool as run_cli_execute  # noqa: E402
from load_skill_tool import TOOL_SCHEMA as LOADSKILL_SCHEMA, execute_tool as load_skill_execute  # noqa: E402
from create_skill_tool import TOOL_SCHEMA as CREATESKILL_SCHEMA, execute_tool as create_skill_execute  # noqa: E402
from file_ops_tool import TOOL_SCHEMA as FILEOPS_SCHEMA, execute_tool as file_ops_execute  # noqa: E402
from office_cli_tool import TOOL_SCHEMA as OFFICECLI_SCHEMA, execute_tool as office_cli_execute  # noqa: E402
from fetch_web_tool import TOOL_SCHEMA as FETCHWEB_SCHEMA, execute_tool as fetch_web_execute  # noqa: E402
from recall_tool import TOOL_SCHEMA as RECALL_SCHEMA, execute_tool as recall_execute  # noqa: E402
from context_manager import ContextManager           # noqa: E402  上下文计量 / 归档 / 压缩
from skills import SkillRegistry, _loose_key         # noqa: E402  Skill 发现与注册
from mcp_client import McpRegistry                   # noqa: E402  MCP 远程工具接入
import app_config                                    # noqa: E402  config.ini 统一配置
import session_store                                 # noqa: E402  会话持久化 / AGENTS.md

# --------------------------------------------------------------------------- #
# 配置：config.ini（cwd → agent 根 → xagent 目录）+ 内置默认值兜底。
# 入口（main.py / tui_app.py）在导入本模块前会先 ensure_config()：
# 一份配置都没有时自动生成 mock 文件并提示用户修改后重启。
# --------------------------------------------------------------------------- #
CFG = app_config.load(Path.cwd())
CONFIG_PATH = CFG.config_path
BASE_URL, _KEY, MODEL = CFG.base_url, CFG.api_key, CFG.model
TIMEOUT = CFG.timeout          # 单次 LLM 请求超时（秒）
MAX_ROUNDS = CFG.max_rounds    # 最多「工具调用→结果回传」轮数，防死循环

# --------------------------------------------------------------------------- #
# 初始化阶段：技能发现与注册（只读 name/description，不读正文）
# --------------------------------------------------------------------------- #
SKILLS = SkillRegistry.discover()

# --------------------------------------------------------------------------- #
# 初始化阶段：MCP 远程工具（异步加载）
#   这里只创建空注册表，不连接 —— TUI 先进界面，MCP 在后台线程连接，
#   加载完成后通过 load_mcp_async 的回调刷新界面；
#   CLI 模式在启动时调 load_mcp_blocking() 同步加载。
#   配置文件：本文件同目录的 .mcp.json，可用环境变量 XAGENT_MCP_CONFIG 覆盖；
#   某个 Server 连不上只记录失败原因，不影响本地工具与其它 Server。
# --------------------------------------------------------------------------- #
MCP_CONFIG_PATH = Path(os.environ.get("XAGENT_MCP_CONFIG")
                       or Path(__file__).resolve().parent / ".mcp.json")
MCP = McpRegistry(MCP_CONFIG_PATH,
                  connect_timeout=CFG.mcp_connect_timeout,
                  call_timeout=CFG.mcp_call_timeout)


def load_mcp_blocking() -> None:
    """同步连接全部 MCP 服务器并刷新工具清单（CLI / --tools 等场景用）。"""
    MCP.load_file(MCP_CONFIG_PATH)
    _refresh_tool_schemas()


def load_mcp_async(on_done=None) -> threading.Thread:
    """后台线程连接 MCP（TUI 先进入界面，加载完成后回调 on_done(registry)）。"""
    def _worker() -> None:
        try:
            MCP.load_file(MCP_CONFIG_PATH)
        except Exception as e:                   # 极端错误也要让界面知道加载结束了
            MCP.failures["<加载>"] = str(e)
            MCP.loaded = True
        finally:
            _refresh_tool_schemas()
            if on_done is not None:
                try:
                    on_done(MCP)
                except Exception:
                    pass
    t = threading.Thread(target=_worker, daemon=True, name="mcp-loader")
    t.start()
    return t


# --------------------------------------------------------------------------- #
# 初始化阶段：上下文管理（Token 计量、阈值告警闸门、归档、压缩、状态栏）
#   归档目录：<项目根>/.agents/context/，可用 XAGENT_CONTEXT_DIR 覆盖
#   阈值 / 默认窗口：config.ini [context] 节
# --------------------------------------------------------------------------- #
CONTEXT = ContextManager(project_root=SKILLS.project_root, model=MODEL,
                         warn_ratio=CFG.warn_ratio,
                         default_window=CFG.default_window)

# 会话存档目录（相对项目根）：config.ini [sessions] dir
SESSIONS_SUB = CFG.sessions_dir


def sessions_root(project_root: Path | None = None) -> Path:
    """会话存档目录（/save /resume /new 用）。"""
    return session_store.sessions_dir(project_root or SKILLS.project_root, SESSIONS_SUB)


def new_session(project_root: Path | None = None) -> tuple[list, dict | None]:
    """新建会话历史：项目根有 AGENTS.md 就注入为第一条 user 消息。

    「一次注入，全程复用」：注入消息随 history 持久化到会话文件，
    后续轮次直接复用历史里的这一条，不再重复注入；每轮请求中它的
    内容与位置完全一致，前缀稳定，利于服务端 KV 缓存命中。
    返回 (历史, 注入事件)，事件由调用方在首次保存会话时写入事件日志。
    """
    return session_store.inject_agents_md(
        [], project_root or SKILLS.project_root)

BASE_PROMPT = (
    "你是 xAgent，一个可以调用工具与技能的智能助手。"
    "可用工具分两类：本地工具（RunCli、fetchWeb、loadSkill、createSkill、fileOps、officeCli、recallContext），"
    "以及 MCP 服务器提供的远程工具（清单见下文）。两类工具用法完全相同。"
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
    "用户问到宠物医院的档案、病历、收费、经营统计等信息时，直接调用对应的 MCP 远程工具查询，"
    "不要用 RunCli 去 curl 接口，也不要编造数据；工具返回错误时如实说明，不要重复同样的调用。"
    "如果对话开头有【上下文压缩摘要】，说明更早的历史已被归档："
    "当摘要里缺少你需要的细节（文件路径、报错、工具返回、用户原话等）时，"
    "调用 recallContext 工具按关键词检索原始记录，不要凭猜测补全，也不要说自己失忆。"
    "回答使用简体中文，简洁清晰。"
)


def system_prompt() -> str:
    """实时拼装 System Prompt（含技能清单与 MCP 工具清单）。

    每次请求都重新渲染，这样刚用 createSkill 建好的技能能立刻出现在清单里。
    """
    section = SKILLS.prompt_section()
    prompt = BASE_PROMPT + ("\n\n" + section if section else "")
    mcp_section = MCP.prompt_section()
    return prompt + mcp_section if mcp_section else prompt


# 兼容旧接口：模块导入时的快照（交互提示等场景可用）
SYSTEM_PROMPT = system_prompt()

# 本轮可用的全部工具声明：本地工具 + MCP 远程工具（动态注册）
LOCAL_SCHEMAS = [RUNCLI_SCHEMA, FETCHWEB_SCHEMA, LOADSKILL_SCHEMA, CREATESKILL_SCHEMA,
                 FILEOPS_SCHEMA, OFFICECLI_SCHEMA, RECALL_SCHEMA]


def tool_schemas() -> list[dict]:
    """实时工具清单：本地工具 + 已连接的 MCP 远程工具。

    MCP 是异步加载的，加载前后清单会变化，所以每次请求现取，
    不再依赖模块导入时的快照。
    """
    return LOCAL_SCHEMAS + MCP.schemas()


def _refresh_tool_schemas() -> None:
    """MCP 加载完成后刷新兼容旧接口的模块级快照。"""
    globals()["TOOL_SCHEMAS"] = tool_schemas()


TOOL_SCHEMAS = list(LOCAL_SCHEMAS)               # 兼容旧引用；MCP 加载后被 _refresh 覆盖


def _chat(messages: list, tools: list | None = None, max_tokens: int | None = None) -> tuple[dict, dict]:
    """调用 chat/completions（非流式），返回 (choices[0].message, usage)。

    tools=None 走默认全量工具；传 [] 表示纯文本调用（压缩摘要用，杜绝 Function Calling）。
    """
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": tool_schemas() if tools is None else tools,   # 工具声明（实时取）
        "tool_choice": "auto" if (tools is None or tools) else "none",
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
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
    return data["choices"][0]["message"], (data.get("usage") or {})


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
    if name == "fetchWeb":
        return fetch_web_execute(arguments)
    if name == "recallContext":              # 检索压缩归档的原始上下文
        return recall_execute(arguments, CONTEXT.archive_dir)
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
    if MCP.owns(name):                       # MCP 远程工具：按映射转发给对应服务器
        return MCP.call(name, arguments)
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


BLOCKED_HINT = ("上下文已占用 {pct}（阈值 70%），已暂停接受新的提示词。"
                "请先执行 /compact 压缩上下文，成功后再继续。")


def run_agent(prompt: str, history: list = (), verbose: bool = True,
              ctx: ContextManager | None = None,
              on_event=None) -> tuple[str, list]:
    """跑一次完整的 Agent 推理。

    返回 (最终回答, 更新后的 history)。verbose=True 时在控制台
    打印每一步「LLM 决策 → 本地执行 → 结果回传」，便于观察全过程。

    on_event: 可选回调，供 TUI 等界面实时展示过程，收到
      {"type": "tool_call", "name": ..., "args": ...}
      {"type": "tool_result", "name": ..., "result": ..., "is_error": bool}

    history 现在保留完整对话轨迹（含 assistant 的 tool_calls 与 role=tool 结果），
    这样工具调用消息也计入上下文、也能被 /compact 归档，符合课程要求。
    """
    ctx = ctx or CONTEXT

    # ---- 闸门：达到 70% 且尚未压缩，拒绝继续处理普通提示词 ----
    if ctx.blocked:
        used = ctx.used_tokens([{"role": "system", "content": system_prompt()}] + list(history))
        return BLOCKED_HINT.format(pct=f"{ctx.ratio(used) * 100:.1f}%"), list(history)

    messages = [{"role": "system", "content": system_prompt()}]
    messages += list(history)
    messages.append({"role": "user", "content": prompt})
    base = list(history)                     # 本轮开始前的历史，出错时原样返回

    for _round in range(1, MAX_ROUNDS + 1):
        messages[0]["content"] = system_prompt()   # 技能清单可能在上一轮被 createSkill 改变
        try:
            msg, usage = _chat(messages)
        except Exception as e:               # 网络/超时/API 错误：给用户明确反馈
            answer = f"[出错] 请求失败：{e}"
            return answer, base
        ctx.note_usage(usage)                # 优先记录 API 返回的真实 Token 用量

        # ---- 情形一：LLM 决定调用工具 ----
        if msg.get("tool_calls"):
            messages.append(_sanitize_message(msg))   # 先记录助手的决策
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except ValueError:
                    args = {}
                if verbose:
                    print(f"  🔧 Agent 决定调用工具：{name}({args})")
                if on_event:
                    on_event({"type": "tool_call", "name": name, "args": args})

                result = dispatch_tool(name, args)          # 本地执行
                if verbose:
                    preview = result if len(result) <= 200 else result[:200] + "…"
                    print(f"  📤 执行结果回传：{preview}")
                if on_event:
                    on_event({"type": "tool_result", "name": name, "result": result,
                              "is_error": result.startswith('{"error"') or '"isError": true' in result
                              or result.startswith("[错误]") or result.startswith("[出错]")})

                messages.append({        # 结果以 role=tool 回传给 LLM
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
            continue                     # 带着 Tool 结果再问 LLM

        # ---- 情形二：LLM 给出最终回答 ----
        answer = msg.get("content") or ""
        messages.append({"role": "assistant", "content": answer})
        return answer, messages[1:]      # 丢掉 system，保留完整轨迹（含工具消息）

    return "（达到最大工具调用轮数上限，已停止）", base


# --------------------------------------------------------------------------- #
# 上下文压缩：/compact 的执行入口
#   压缩期间只允许「纯文本 LLM 调用」——tools=[] + tool_choice=none，
#   从协议层就杜绝了压缩过程中再触发 Function Calling。
# --------------------------------------------------------------------------- #
def summarize_chat(system: str, user: str, max_tokens: int | None = None) -> str:
    """给 context_manager 用的摘要调用：不带任何工具，只返回文本。"""
    msg, usage = _chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        tools=[], max_tokens=max_tokens or CFG.summary_tokens,
    )
    CONTEXT.note_usage(usage)                # 摘要调用本身也消耗 Token，记账
    return msg.get("content") or ""


def compact_session(history: list, ctx: ContextManager | None = None,
                    verbose: bool = True, printer=print) -> tuple[list, dict]:
    """执行一次完整压缩：归档 → 摘要 → 替换历史。失败抛 CompactError。"""
    ctx = ctx or CONTEXT
    return ctx.compact(history, summarize_chat, verbose=verbose, printer=printer)
