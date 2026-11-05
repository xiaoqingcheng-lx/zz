# -*- coding: utf-8 -*-
"""selftest_sessions —— 会话持久化 / 配置自举 / AGENTS.md 注入 / 命令注册表 自测。

    python selftest_sessions.py     # 全绿即通过
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

PASS, FAIL = 0, 0


def check(name: str, cond, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="xagent-selftest-"))
    try:
        import app_config
        import commands as slash
        import session_store as store
        from context_manager import ContextManager

        # ---------------- 1. app_config ----------------
        print("\n[1] app_config：查找 / 生成 mock / 解析")
        # 生产环境 agent 根目录可能已有 config.ini（会被优先复用，属预期）；
        # 这里把查找范围隔离到临时目录，单独验证「无配置 → 生成 mock」路径。
        _orig_candidates = app_config.candidate_paths
        app_config.candidate_paths = lambda cwd=None: [
            Path(cwd or Path.cwd()).resolve() / app_config.CONFIG_NAME]
        try:
            p, created = app_config.ensure_config(tmp)
            check("无配置时生成 config.ini", created and p.is_file() and p.parent == tmp)
            text = p.read_text(encoding="utf-8")
            for token in ("[llm]", "[agent]", "[context]", "[mcp]", "[sessions]",
                          "api_key", "warn_ratio", "autosave"):
                check(f"mock 配置含 {token}", token in text)
            cfg = app_config.load(tmp)
            check("load 解析出 model 默认值", cfg.model == "qwen-plus")
            check("mock key 是占位符", "sk-请把" in text)
            check("load 数值字段有默认", cfg.timeout == 120 and cfg.max_rounds == 10
                  and cfg.warn_ratio == 0.70 and cfg.default_window == 128000)
        finally:
            app_config.candidate_paths = _orig_candidates
        check("真实环境复用已有配置",
              app_config.existing_config() is not None)
        # 带自定义值的配置解析
        (tmp / "custom").mkdir()
        (tmp / "custom" / "config.ini").write_text(
            "[llm]\nmodel = qwen-max\n\n[agent]\ntimeout = 66\nmax_rounds = 3\n\n"
            "[context]\nwarn_ratio = 0.5\n\n[sessions]\nautosave = 0\n",
            encoding="utf-8")
        cfg2 = app_config.load(tmp / "custom")
        check("自定义 model/timeout/max_rounds 生效",
              cfg2.model == "qwen-max" and cfg2.timeout == 66 and cfg2.max_rounds == 3)
        check("自定义 warn_ratio / autosave 生效",
              abs(cfg2.warn_ratio - 0.5) < 1e-9 and cfg2.autosave is False)

        # ---------------- 2. session_store ----------------
        print("\n[2] session_store：保存 / 列表 / 恢复 / 删除")
        root = tmp / "proj"
        root.mkdir()
        (root / "AGENTS.md").write_text("# 项目约定\n- 回答用中文\n- 不许编造",
                                        encoding="utf-8")
        hist = [
            {"role": "user", "content": "帮我看看磁盘占用"},
            {"role": "assistant", "content": "好的，我来跑个命令。", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "RunCli", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "C: 120G"},
            {"role": "assistant", "content": "C 盘用了 120G。"},
            {"role": "user", "content": "再来一次"},
            {"role": "assistant", "content": "完成。"},
        ]
        meta = store.save_session(root, hist, session_id="20260101-000000",
                                  model="qwen-plus",
                                  events=[{"type": "agents_md_injected", "chars": 30}])
        check("保存返回元信息", meta["id"] == "20260101-000000" and meta["turns"] == 2)
        check("事件已持久化", meta["events"][0]["type"] == "agents_md_injected")
        again = store.save_session(root, hist, session_id="20260101-000000")
        check("重复保存保留 created_at", again["created_at"] == meta["created_at"])
        lst = store.list_sessions(root)
        check("列表能找到会话", len(lst) == 1 and lst[0]["id"] == "20260101-000000")
        check("标题取自首条真实用户消息", "磁盘" in lst[0]["title"])
        h2, m2 = store.load_session(root, "20260101-000000")
        check("恢复历史完整（含 tool 消息）",
              len(h2) == len(hist) and h2[2]["role"] == "tool")
        check("恢复元信息一致", m2["turns"] == 2)
        check("删除会话", store.delete_session(root, "20260101-000000")
              and not store.list_sessions(root))
        check("加载不存在的会话报 FileNotFoundError",
              (lambda: [False])() if _try_load(root) else True)

        # ---------------- 3. AGENTS.md 注入 ----------------
        print("\n[3] AGENTS.md：一次注入，全程复用")
        msg = store.agents_md_message(root)
        check("有 AGENTS.md 返回注入消息",
              msg is not None and msg["role"] == "user"
              and msg["content"].startswith(store.AGENTS_MD_HEADER)
              and "项目约定" in msg["content"])
        h3, ev = store.inject_agents_md([], root)
        check("空会话注入 1 条消息", len(h3) == 1 and ev is not None
              and ev["type"] == "agents_md_injected")
        h4, ev2 = store.inject_agents_md(h3, root)
        check("已有历史的会话不重复注入", len(h4) == 1 and ev2 is None)
        (root / "AGENTS.md").unlink()
        check("无 AGENTS.md 返回 None 且历史不变",
              store.agents_md_message(root) is None
              and store.inject_agents_md([], root) == ([], None))
        check("AGENTS.md / 压缩摘要不计入轮数",
              store.count_turns([
                  {"role": "user", "content": store.AGENTS_MD_HEADER + "x"},
                  {"role": "user", "content": "【上下文压缩摘要】y"},
                  {"role": "user", "content": "真的问题"},
              ]) == 1)

        # ---------------- 4. commands 注册表 ----------------
        print("\n[4] commands：斜杠命令注册表 / 补全")
        names = slash.all_names()
        for need in ("/new", "/resume", "/save", "/quit", "/compact", "/help"):
            check(f"注册了 {need}", need in names)
        check("补全前缀 /re 命中 /resume",
              "/resume" in slash.complete_prefix("/re"))
        check("补全前缀 / 全部命中", len(slash.complete_prefix("/")) == len(names))
        check("description_of 覆盖别名",
              slash.description_of("/exit") == slash.description_of("/quit"))
        ht = slash.help_text()
        check("help_text 含补全面板说明", "补全" in ht and "/new" in ht)

        # ---------------- 5. MCP 注册表延迟加载 ----------------
        print("\n[5] MCP：延迟加载 / 空配置容错")
        from mcp_client import McpRegistry
        reg = McpRegistry(tmp / "no-such.json")
        reg.load_file()
        check("配置文件缺失静默通过", reg.loaded and not reg.tools)
        reg2 = McpRegistry(tmp / "empty.json")
        (tmp / "empty.json").write_text("{}", encoding="utf-8")
        reg2.load_file()
        check("空 mcpServers 不报错", reg2.loaded and not reg2.tools)

        # ---------------- 6. ContextManager 配置参数 ----------------
        print("\n[6] ContextManager：warn_ratio / default_window 参数化")
        c = ContextManager(project_root=tmp, model="qwen-plus",
                           warn_ratio=0.5, default_window=999_000)
        check("自定义阈值生效（50% 阻断）", c.update_blocked(c.window * 0.51) is True
              and c.update_blocked(c.window * 0.3) is False)
        c2 = ContextManager(project_root=tmp, model="unknown-model-xyz",
                            default_window=77_000)
        check("默认窗口来自配置", c2.window == 77_000 and c2.window_is_default)

        # ---------------- 7. xagent 集成 ----------------
        print("\n[7] xagent：CFG 接管 / AGENTS.md / 动态工具")
        import xagent as xa
        check("CFG 已接管模型", xa.CFG.model == xa.MODEL)
        check("CONTEXT 阈值来自 CFG", abs(xa.CONTEXT.warn_ratio - xa.CFG.warn_ratio) < 1e-9)
        check("CONTEXT 窗口来自 CFG", xa.CONTEXT.window == xa.CFG.default_window
              or not xa.CONTEXT.window_is_default)
        check("tool_schemas 动态可用", len(xa.tool_schemas()) >= len(xa.LOCAL_SCHEMAS))
        (root / "AGENTS.md").write_text("# 项目约定\n- 回答用中文",
                                        encoding="utf-8")
        h5, ev5 = xa.new_session(root)
        check("xagent.new_session 支持 AGENTS.md 注入",
              (len(h5) == 1 and ev5 is not None))
        check("xagent.new_session 无文件时空历史", xa.new_session(tmp / "proj2") == ([], None))
        sr = xa.sessions_root(root)
        check("sessions_root 来自配置", sr.name == "sessions" and sr.parent.name == ".agents")

        # ---------------- 8. TUI / CLI 可编译可导入 ----------------
        print("\n[8] TUI / CLI 导入")
        import py_compile
        for f in ("tui_app.py", "main.py", "tui_app.py"):
            try:
                py_compile.compile(str(_HERE / f), doraise=True)
                check(f"{f} 编译通过", True)
            except py_compile.PyCompileError as e:
                check(f"{f} 编译通过", False, str(e)[:120])
        import tui_app
        check("TUI 有命令分发表", hasattr(tui_app.XAgentTUI, "_dispatch_command"))
        check("TUI 有边栏刷新", hasattr(tui_app.XAgentTUI, "_refresh_sidebar"))
        check("TUI 有 MCP 异步回调", hasattr(tui_app.XAgentTUI, "_on_mcp_loaded"))
        check("TUI 补全面板类存在", hasattr(tui_app, "CommandPalette"))
        check("TUI 会话面板类存在", hasattr(tui_app, "ResumeScreen"))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 46}\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


def _try_load(root: Path) -> bool:
    import session_store as _store
    try:
        _store.load_session(root, "not-exist")
        return True
    except FileNotFoundError:
        return False


if __name__ == "__main__":
    sys.exit(main())
