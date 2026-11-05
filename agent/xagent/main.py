# -*- coding: utf-8 -*-
"""xAgent 入口：默认终端交互对话，--demo 一次性演示，--skills 看技能，--mcp 看 MCP。

    python main.py                     # 交互模式（输入 /help 看命令，exit 退出）
    python main.py --tui               # 启动 Textual 全屏界面（同 tui_app.py）
    python main.py --demo "提示词"     # 单次运行，完整打印工具调用过程
    python main.py --skills            # 打印技能注册表与注入的 System Prompt 片段
    python main.py --mcp               # 打印 MCP 服务器连接结果与注册到的工具
    python main.py --tools             # 列出本轮可用的全部工具（本地 + MCP）
    python main.py --context           # 只看上下文用量与归档情况

交互命令（输入 / 可列出全部命令）：
    /new       新建会话（自动保存当前会话历史）
    /resume    列出历史会话，输入编号恢复
    /save      保存当前会话
    /quit      保存并退出
    /compact   手动触发上下文压缩（归档原始记录 → LLM 生成摘要 → 替换历史）
    /history   查看当前会话完整历史
    /model     查看当前模型与上下文窗口
    /config    查看配置文件位置与关键参数
    /context   查看上下文用量、阈值与归档文件
    /help      帮助
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

# ---- 配置自举：必须在导入 xagent 之前保证 config.ini 存在 ----
import app_config                                          # noqa: E402
_CONFIG_PATH, _CONFIG_CREATED = app_config.ensure_config(_HERE.parent)
if _CONFIG_CREATED:
    print("=" * 60)
    print(app_config.MOCK_NOTICE.format(path=_CONFIG_PATH))
    print("=" * 60)
    try:
        input("按回车键退出，修改 config.ini 后重新启动即可。")
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(0)

import context_manager as cm                               # noqa: E402
import session_store as store                              # noqa: E402
import commands as slash                                   # noqa: E402
import xagent as xa                                       # noqa: E402
from xagent import (CONTEXT, MCP, SKILLS, TOOL_SCHEMAS,    # noqa: E402
                    compact_session, load_mcp_blocking, new_session,
                    run_agent, system_prompt, tool_schemas)

USE_COLOR = cm.enable_ansi()

HELP_TEXT = slash.help_text()


def _all_messages(history: list) -> list:
    """状态栏要计量的完整上下文：System Prompt + 对话历史 + 工具消息。"""
    return [{"role": "system", "content": system_prompt()}] + list(history)


def _status_line(history: list) -> str:
    return CONTEXT.status_bar(_all_messages(history), USE_COLOR)


def show_status(history: list) -> None:
    """在醒目位置打印一行上下文状态（含窗口大小、百分比、占用条）。"""
    print(_status_line(history))


def show_context_detail(history: list) -> None:
    """上下文用量明细 + 归档列表。"""
    msgs = _all_messages(history)
    used = CONTEXT.used_tokens(msgs)
    ratio = CONTEXT.ratio(used)
    print()
    print("─" * 46)
    print(f"模型            {CONTEXT.model}")
    print(f"上下文窗口      {cm.format_k(CONTEXT.window)} Tokens"
          + ("（默认值，未能识别模型）" if CONTEXT.window_is_default else ""))
    print(f"当前占用        {cm.format_k(used)} Tokens / {ratio * 100:.1f}%"
          f"（来源：{'API usage' if CONTEXT.api_source == 'api' else '字符估算'}）")
    print(f"告警阈值        {CONTEXT.warn_ratio * 100:.0f}%"
          + ("　→ 已触发，需 /compact" if CONTEXT.blocked else "　→ 未触发"))
    print(f"消息条数        {len(history)}（不含 System Prompt）")
    print(f"归档目录        {CONTEXT.archive_dir}")
    archives = cm.list_archives(CONTEXT.archive_dir)
    if archives:
        print(f"已有归档        {len(archives)} 个")
        for p in archives[:5]:
            size = p.stat().st_size / 1024
            print(f"  - {p.stem}  ({size:.1f} KB)")
        if len(archives) > 5:
            print(f"  … 另有 {len(archives) - 5} 个")
    else:
        print("已有归档        0 个（执行 /compact 后会生成）")
    print("─" * 46)


def do_compact(history: list) -> list:
    """执行 /compact：成功后返回替换后的历史；失败保留原历史。"""
    if not history:
        print("ℹ️ 当前会话还没有历史消息，不需要压缩。")
        return history

    before = cm.estimate_messages_tokens(history)
    print(f"\n⚙️ 开始压缩上下文（{len(history)} 条消息，约 {cm.format_k(before)} Tokens）"
          f"——期间不执行任何工具调用，也不处理新任务。")
    try:
        new_history, info = compact_session(history, ctx=CONTEXT, verbose=True)
    except cm.CompactError as e:
        print(cm.colorize(f"❌ 压缩失败：{e}", "red", USE_COLOR))
        print("   原有上下文完整保留，可直接重新执行 /compact。")
        return history
    except Exception as e:                       # 网络 / API 异常
        print(cm.colorize(f"❌ 压缩失败：{e}", "red", USE_COLOR))
        print("   原有上下文完整保留，可直接重新执行 /compact。")
        return history

    after = cm.estimate_messages_tokens(new_history)
    print(cm.colorize("✅ 压缩完成", "green", USE_COLOR))
    print(f"   历史消息：{info['replaced']} 条 → {len(new_history)} 条（摘要）")
    print(f"   Token：约 {cm.format_k(before)} → 约 {cm.format_k(after)}")
    print(f"   归档编号：{info['id']}")
    print(f"   归档文件：{info['path']}")
    print("   摘要末尾已追加归档说明；需要旧细节时可让 Agent 调用 recallContext 检索。")
    print()
    for line in cm.describe_block(info):          # 「本次压缩了什么」明细
        print(line)
    print("   输入 /logs 可查看历次压缩记录。\n")
    return new_history


def show_logs(blocks: int = 3) -> None:
    """查看最近几次压缩日志：每次压了哪些内容、摘要结构、归档编号。"""
    log_path = CONTEXT.archive_dir / cm.COMPACT_LOG_NAME
    text = cm.read_compact_log(log_path, blocks)
    print()
    if not text:
        print(f"暂无压缩记录（{log_path} 不存在或为空）。执行一次 /compact 后会生成。\n")
        return
    print(text)
    print(f"\n完整日志：{log_path}\n")


def show_skills() -> None:
    """打印技能注册结果（发现 → 注册 → 注入 Prompt 的中间产物）。"""
    print(SKILLS.summary())
    if SKILLS.skills:
        print("\n--- 注入 System Prompt 的技能清单 ---")
        print(SKILLS.prompt_section())
    else:
        print("\n（没有可用技能：请在 .agents\\skills\\ 下放置含 SKILL.md 的子目录）")


def show_mcp() -> None:
    """打印 MCP 连接与工具注册结果。"""
    print(f"配置文件：{MCP.config_path}")
    print()
    print(MCP.summary())
    if MCP.tools:
        print("\n--- 注册给 LLM 的 MCP 工具 ---")
        for t in MCP.tools.values():
            params = ", ".join((t.schema.get("properties") or {}).keys()) or "无参数"
            print(f"  {t.exposed:<24} [{t.server}] 参数：{params}")
            print(f"      原始工具名：{t.name}")


def show_tools() -> None:
    """列出本轮全部工具声明（本地 + MCP）。"""
    schemas = tool_schemas()
    print(f"共 {len(schemas)} 个工具：")
    for s in schemas:
        fn = s["function"]
        desc = (fn.get("description") or "").replace("\n", " ")[:60]
        print(f"  - {fn['name']:<24} {desc}")


def show_model() -> None:
    print(f"模型            {CONTEXT.model}")
    print(f"上下文窗口      {cm.format_k(CONTEXT.window)} Tokens"
          + ("（默认值）" if CONTEXT.window_is_default else ""))
    print(f"告警阈值        {CONTEXT.warn_ratio * 100:.0f}%")
    print(f"API 地址        {xa.CFG.base_url}")


def show_config() -> None:
    cfg = xa.CFG
    print(f"配置文件        {cfg.config_path}"
          + ("　（示例配置：请修改 api_key 后重启）" if cfg.is_mock else ""))
    print(f"base_url        {cfg.base_url}")
    print(f"model           {cfg.model}")
    print(f"timeout         {cfg.timeout}s ｜ max_rounds {cfg.max_rounds} ｜ "
          f"summary_tokens {cfg.summary_tokens}")
    print(f"warn_ratio      {cfg.warn_ratio} ｜ default_window {cfg.default_window}")
    print(f"sessions_dir    {cfg.sessions_dir} ｜ autosave {'开' if cfg.autosave else '关'}")
    print(f"MCP 配置        {MCP.config_path} ｜ 已加载 {'是' if MCP.loaded else '否'}")


def show_history(history: list) -> None:
    """查看当前会话完整历史（含注入消息与工具调用轨迹）。"""
    if not history:
        print("当前会话还没有历史消息。")
        return
    print(f"当前会话历史（{len(history)} 条）：")
    print(cm.render_history_view(history))


# --------------------------------------------------------------------------- #
# 会话命令（/new /resume /save）
# --------------------------------------------------------------------------- #
def save_session(session_id: str, history: list, events: list | None) -> dict:
    return store.save_session(SKILLS.project_root, history, session_id=session_id,
                              sub=xa.SESSIONS_SUB,
                              model=CONTEXT.model, events=events)


def cmd_new(session_id: str, history: list, events: list) -> tuple[str, list, list]:
    """/new：自动保存当前会话，返回 (新会话ID, 新历史, 新事件)。"""
    if history:
        meta = save_session(session_id, history, events)
        print(f"💾 已保存当前会话 {meta['id']}（{meta['turns']} 轮）"
              f" → {meta.get('path', '')}")
    new_history, agents_event = new_session()
    new_events = [agents_event] if agents_event else []
    new_id = store.new_session_id()
    CONTEXT.reset_usage()
    print(f"—— 新会话 {new_id} ——")
    if agents_event:
        print("已注入项目根 AGENTS.md（一次注入，全程复用）。")
    print()
    return new_id, new_history, new_events


def cmd_resume(session_id: str, history: list, events: list) -> tuple[str, list, list]:
    """/resume：列出历史会话，输入编号恢复。"""
    sessions = store.list_sessions(SKILLS.project_root,
                                   xa.SESSIONS_SUB)
    if not sessions:
        print("暂无历史会话（.agents/sessions/ 为空）。")
        return session_id, history, events
    print("\n历史会话（按更新时间倒序）：")
    for i, s in enumerate(sessions[:12], 1):
        print(f"  [{i}] {s['title']}  ·  {s['id']}  ·  "
              f"{s['turns']} 轮 / {s['messages']} 条  ·  {s['updated_at']}")
    raw = input("输入编号恢复会话（直接回车取消）：").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= min(12, len(sessions))):
        print("已取消。\n")
        return session_id, history, events
    picked = sessions[int(raw) - 1]
    if history:
        meta = save_session(session_id, history, events)
        print(f"💾 已保存当前会话 {meta['id']} → {meta.get('path', '')}")
    try:
        new_history, meta = store.load_session(
            SKILLS.project_root, picked["id"], xa.SESSIONS_SUB)
    except (OSError, ValueError) as e:
        print(f"恢复失败：{e}")
        return session_id, history, events
    CONTEXT.reset_usage()
    print(f"—— 已恢复会话 {meta.get('id', picked['id'])} ——\n"
          f"   标题：{meta.get('title', '')} · {meta.get('turns', 0)} 轮 · "
          f"{len(new_history)} 条消息\n")
    return meta.get("id", picked["id"]), new_history, []


def demo(prompt: str) -> None:
    """一次性演示：完整展示 Agent 调用工具的全过程。"""
    load_mcp_blocking()
    print(f"用户：{prompt}")
    history, _ = new_session()
    answer, history = run_agent(prompt, history, ctx=CONTEXT)
    print(f"\nxAgent：{answer}")
    print()
    show_status(history)


def interactive() -> None:
    load_mcp_blocking()
    history, agents_event = new_session()
    events: list[dict] = [agents_event] if agents_event else []
    session_id = store.new_session_id()

    print("xAgent（可调用本地工具、技能与 MCP 远程工具；输入 / 看命令，/help 帮助）")
    print(SKILLS.summary())
    print(MCP.summary())
    if events:
        print("已注入项目根 AGENTS.md（一次注入，全程复用）。")
    print(f"会话编号：{session_id}（每轮结束自动保存）")
    print(f"上下文归档目录：{CONTEXT.archive_dir}\n")
    show_status(history)

    while True:
        # ---- 输入闸门：达到阈值后只接受命令 ----
        warn = CONTEXT.warning_line(_all_messages(history), USE_COLOR)
        if warn:
            print(warn)
        try:
            prompt = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not prompt:
            continue
        low = prompt.lower()
        if low in ("exit", "quit", "q", "/exit", "/quit"):
            break

        # ---- 命令 ----
        if low.startswith("/"):
            if low in ("/help", "/?"):
                print(HELP_TEXT)
            elif low in ("/compact", "/compress"):
                history = do_compact(history)
            elif low in ("/context", "/status"):
                show_context_detail(history)
            elif low in ("/logs", "/log"):
                show_logs()
            elif low == "/history":
                show_history(history)
            elif low == "/new":
                session_id, history, events = cmd_new(session_id, history, events)
            elif low in ("/resume", "/sessions"):
                session_id, history, events = cmd_resume(session_id, history, events)
            elif low == "/save":
                if history:
                    meta = save_session(session_id, history, events)
                    print(f"💾 会话已保存 {meta['id']}（{meta['turns']} 轮 / "
                          f"{meta['messages']} 条） → {meta.get('path', '')}\n")
                else:
                    print("当前会话为空，没有可保存的内容。")
            elif low == "/model":
                show_model()
            elif low == "/config":
                show_config()
            elif low == "/skills":
                show_skills()
            elif low == "/mcp":
                show_mcp()
            elif low == "/tools":
                show_tools()
            elif low == "/clear":
                history, events = [], []
                CONTEXT.reset_usage()
                print("—— 会话已清空 ——\n")
            else:
                print(f"未知命令：{prompt}（输入 / 查看可用命令）")
            show_status(history)
            continue

        # ---- 普通提示词：达到阈值就拒绝 ----
        if CONTEXT.blocked:
            print(cm.colorize(
                f"⛔ 上下文已占用 {CONTEXT.ratio(CONTEXT.used_tokens(_all_messages(history))) * 100:.1f}%，"
                f"已暂停处理新任务。请先执行 /compact。", "red", USE_COLOR))
            continue

        answer, history = run_agent(prompt, history, ctx=CONTEXT)
        print(f"xAgent：{answer}\n")

        # ---- 每轮结束自动保存会话（config.ini [sessions] autosave 可关） ----
        if xa.CFG.autosave and store.count_turns(history):
            try:
                save_session(session_id, history, events)
                events = []
            except Exception:
                pass

        # ---- 每次响应后检查上下文用量（含工具消息），越过阈值就挂闸门 ----
        used = CONTEXT.used_tokens(_all_messages(history))
        CONTEXT.update_blocked(used)
        show_status(history)


def run_tui() -> None:
    """启动 Textual 全屏界面（同一套内核，界面换成带状态栏的 TUI）。"""
    from tui_app import XAgentTUI
    XAgentTUI().run()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--tui":
        run_tui()
    elif args and args[0] == "--demo":
        demo(args[1] if len(args) > 1 else "查看当前目录下有哪些文件")
    elif args and args[0] == "--skills":
        show_skills()
    elif args and args[0] == "--mcp":
        load_mcp_blocking()
        show_mcp()
    elif args and args[0] == "--tools":
        load_mcp_blocking()
        show_tools()
    elif args and args[0] == "--context":
        show_context_detail([])
    elif args and args[0] == "--config":
        load_mcp_blocking()
        show_config()
    else:
        interactive()
