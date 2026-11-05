# -*- coding: utf-8 -*-
"""上下文压缩 + 历史检索自测（全程本地，不调用真实 LLM）。

覆盖：Token 计量 → 窗口识别 → 70% 闸门 → 归档落盘 → 摘要替换 → 分片压缩 → recallContext 检索。

用法：python selftest_context.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import context_manager as cm                       # noqa: E402
from context_manager import ContextManager, CompactError  # noqa: E402
import recall_tool                                 # noqa: E402

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


TMP = Path(tempfile.mkdtemp(prefix="xagent_ctx_"))
ARCH = TMP / ".agents" / "context"


def make_history():
    """一段含 System / 用户 / 工具调用 / 工具结果的真实结构历史。"""
    return [
        {"role": "user", "content": "帮我把 D:\\大语言模型\\agent\\xagent\\main.py 里的日志改成 logging"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "RunCli", "arguments": json.dumps({"command": "dir main.py"}, ensure_ascii=False)},
        }]},
        {"role": "tool", "tool_call_id": "call_1", "content": "main.py 3,102 bytes"},
        {"role": "assistant", "content": "目录里确实有 main.py，接下来我改日志。"},
        {"role": "user", "content": "记得保留中文注释，不要动格式。"},
    ]


print("① Token 估算")
check("空文本 → 0", cm.estimate_text_tokens("") == 0)
check("中文 100 字约 100 token", 95 <= cm.estimate_text_tokens("上" * 100) <= 105,
      cm.estimate_text_tokens("上" * 100))
check("英文 350 字符约 100 token", 95 <= cm.estimate_text_tokens("a" * 350) <= 105,
      cm.estimate_text_tokens("a" * 350))
msg_with_tool = {"role": "assistant", "content": None,
                 "tool_calls": [{"function": {"name": "RunCli", "arguments": '{"command": "ls -la"}'}}]}
check("工具调用参数计入 Token", cm.estimate_message_tokens(msg_with_tool) > 10,
      cm.estimate_message_tokens(msg_with_tool))
check("整段消息累加", cm.estimate_messages_tokens(make_history()) > 50)
check("估算值随内容增长", cm.estimate_messages_tokens(make_history() * 2) >
      cm.estimate_messages_tokens(make_history()))

print("\n② 上下文窗口识别")
w, d = cm.resolve_window("qwen-plus")
check("qwen-plus → 131072 且非默认", (w, d) == (131072, False), f"{(w, d)}")
w, d = cm.resolve_window("some-unknown-model")
check("未知模型 → 128k 且标记默认", (w, d) == (128_000, True), f"{(w, d)}")
w, d = cm.resolve_window("qwen-plus-2025-09-15")
check("带版本后缀仍能识别", (w, d) == (131072, False), f"{(w, d)}")
os.environ["XAGENT_CONTEXT_WINDOW"] = "64000"
w, d = cm.resolve_window("some-unknown-model")
check("环境变量可覆盖窗口", (w, d) == (64000, False), f"{(w, d)}")
os.environ.pop("XAGENT_CONTEXT_WINDOW")
check("format_k 显示成 128k", cm.format_k(131072) == "128k", cm.format_k(131072))
check("format_k 小数字原样", cm.format_k(999) == "999", cm.format_k(999))

print("\n③ 状态栏与 70% 闸门")
bar = cm.render_status_bar(16384, 131072, False, use_color=False)
check("状态栏含已用/窗口", "16k / 128k" in bar, bar)
check("状态栏含百分比", "12.5%" in bar, bar)
check("状态栏含占用条", "█" in bar, bar)
bar2 = cm.render_status_bar(1000, 128_000, True, use_color=False)
check("窗口为默认值时标注「默认」", "（默认）" in bar2, bar2)

ctx = ContextManager(project_root=TMP, model="qwen-plus", archive_dir=ARCH)
ctx.note_usage({"prompt_tokens": 100_000})
check("API usage 优先于估算", ctx.used_tokens([{"role": "user", "content": "hi"}]) >= 100_000)
check("超过 70% 触发闸门", ctx.update_blocked(100_000) is True)
check("blocked 状态为真", ctx.blocked is True)
ctx.reset_usage()
check("reset 后解除闸门", ctx.blocked is False and ctx.api_tokens == 0)
check("未达阈值不告警", ctx.warning_line([{"role": "system", "content": "x" * 100}]) == "")
ctx.note_usage({"prompt_tokens": 100_000})
check("超阈值时给出 /compact 提示", "/compact" in ctx.warning_line([]))

print("\n④ 原始上下文归档")
ctx = ContextManager(project_root=TMP, model="qwen-plus", archive_dir=ARCH)
history = [{"role": "system", "content": "system prompt"}] + make_history()
aid = ctx.new_archive_id()
check("归档编号形如 YYYYMMDD-HHMMSS",
      len(aid) == 15 and aid[8] == "-" and aid.replace("-", "").isdigit(), aid)
path = ctx.save_archive(history, aid)
check("归档文件已生成", path.is_file(), str(path))
check("文件名为 <编号>.jsonl", path.name == f"{aid}.jsonl", path.name)
lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
check("首行是 _meta", "_meta" in lines[0], str(lines[0])[:60])
check("消息条数完整", len(lines) - 1 == len(history), f"{len(lines) - 1} vs {len(history)}")
check("消息顺序保留", [x.get("index") for x in lines[1:]] == list(range(len(history))))
check("角色保留", [x.get("role") for x in lines[1:]] == [m["role"] for m in history])
check("工具调用参数保留", lines[3]["tool_calls"][0]["function"]["arguments"].startswith('{"command"'))
check("工具返回结果保留", lines[4]["content"] == "main.py 3,102 bytes")
check("tool_call_id 保留", lines[4]["tool_call_id"] == "call_1")
check("中文内容未转义", "中文注释" in path.read_text(encoding="utf-8"))
check("无残留 .tmp 文件", not list(ARCH.glob("*.tmp")))

bad_root = TMP / "not_a_dir"
bad_root.write_text("x", encoding="utf-8")          # 用文件占住目录位置，制造写入失败
ctx_bad = ContextManager(project_root=TMP, model="qwen-plus", archive_dir=bad_root / "sub")
try:
    ctx_bad.save_archive(history, "20260101-000000")
    check("归档失败应抛 CompactError", False, "没有抛异常")
except CompactError as e:
    check("归档失败抛 CompactError", "归档失败" in str(e), str(e))

print("\n⑤ 压缩：摘要替换历史")
calls = []


def fake_chat(system, user, max_tokens=6000):
    calls.append((system, user))
    return "# 工作摘要\n\n- 用户要求把 main.py 的日志改成 logging\n- 已确认 main.py 存在"


ctx = ContextManager(project_root=TMP, model="qwen-plus", archive_dir=ARCH)
long_hist = make_history() * 20                      # 模拟一段已经攒了很久的会话
new_history, info = ctx.compact(long_hist, fake_chat, verbose=False, printer=lambda *_: None)
check("压缩只调一次 LLM（历史不长）", len(calls) == 1, str(len(calls)))
check("传给 LLM 的是压缩专用 Prompt", "上下文管理助手" in calls[0][0])
check("历史被替换成 1 条摘要", len(new_history) == 1, str(len(new_history)))
check("摘要消息角色为 user", new_history[0]["role"] == "user")
check("摘要正文被保留", "改成 logging" in new_history[0]["content"])
check("末尾追加归档说明", "此前上下文已于" in new_history[0]["content"])
check("归档说明含编号", info["id"] in new_history[0]["content"])
check("归档说明提示 recallContext", "recallContext" in new_history[0]["content"])
check("归档文件确实存在", Path(info["path"]).is_file(), info["path"])
check("返回信息记录替换条数", info["replaced"] == len(long_hist), str(info["replaced"]))
check("压缩后解除闸门", ctx.blocked is False)
check("压缩后用量读数重置", ctx.api_tokens == 0)
check("压缩后 Token 大幅下降",
      cm.estimate_messages_tokens(new_history) < cm.estimate_messages_tokens(long_hist) / 5,
      f"{cm.estimate_messages_tokens(new_history)} vs {cm.estimate_messages_tokens(long_hist)}")

print("\n⑥ 压缩失败要保留原上下文")
def boom(system, user, max_tokens=6000):
    raise RuntimeError("网络断了")


ctx2 = ContextManager(project_root=TMP, model="qwen-plus", archive_dir=ARCH)
before_files = len(list(ARCH.glob("*.jsonl")))
try:
    ctx2.compact(make_history(), boom, verbose=False, printer=lambda *_: None)
    check("LLM 失败应抛异常", False, "没有抛异常")
except RuntimeError as e:
    check("LLM 失败向上抛异常", "网络断了" in str(e))
check("失败时归档已先落盘", len(list(ARCH.glob("*.jsonl"))) == before_files + 1)
check("失败时未改动 last_compact", ctx2.last_compact is None)

try:
    ctx2.compact([], fake_chat, verbose=False, printer=lambda *_: None)
    check("空历史应报错", False, "没有抛异常")
except CompactError as e:
    check("空历史抛 CompactError", "没有可压缩" in str(e), str(e))

try:
    ctx2.compact(make_history(), lambda s, u, max_tokens=6000: "   ", verbose=False, printer=lambda *_: None)
    check("空摘要应报错", False, "没有抛异常")
except CompactError as e:
    check("空摘要抛 CompactError", "没有返回摘要" in str(e), str(e))

print("\n⑦ 历史转文本")
text = cm.render_transcript([{"role": "system", "content": "SECRET_SYS_PROMPT"}] + make_history(),
                            "20261022-153000")
check("渲染含角色", "### [1] user" in text, text[:80])
check("渲染含工具调用参数", "RunCli" in text and "dir main.py" in text)
check("渲染含 tool_call_id", "tool_call_id=call_1" in text)
check("渲染跳过 System Prompt 正文", "SECRET_SYS_PROMPT" not in text and "System Prompt 每轮重建" in text)
long_text = cm.render_transcript([{"role": "tool", "content": "长" * 5000}])
check("超长单条被截断并标注", "已截断" in long_text)

chunks = cm.split_by_tokens("段落内容。" * 4000, 2000)
check("长文本被切成多片", len(chunks) > 1, str(len(chunks)))
check("每片不超过预算太多", all(cm.estimate_text_tokens(c) < 2600 for c in chunks))

print("\n⑧ 历史过长时自动分片压缩")
small = ContextManager(project_root=TMP, model="unknown", window=2000, archive_dir=ARCH)
calls.clear()
small.compact(make_history() * 40, fake_chat, verbose=False, printer=lambda *_: None)
check("分片时调用多于一次", len(calls) > 1, str(len(calls)))
check("最后仍用压缩专用 Prompt 汇总", "上下文管理助手" in calls[-1][0])
check("分片提示词是片段摘要版", "一部分" in calls[0][0])

print("\n⑨ recallContext 检索")
archive_dir = ARCH
aid_x = "20261022-153000"
path_x = archive_dir / f"{aid_x}.jsonl"
with open(path_x, "w", encoding="utf-8") as f:
    for i, m in enumerate(make_history()):
        f.write(json.dumps({"index": i, **m}, ensure_ascii=False) + "\n")
path_y = archive_dir / "20261023-090000.jsonl"
with open(path_y, "w", encoding="utf-8") as f:
    f.write(json.dumps({"index": 0, "role": "user", "content": "另一段历史，提到 pandas 和 numpy"},
                       ensure_ascii=False) + "\n")

res = recall_tool.search(archive_dir, "logging")
check("关键词命中", res["matched"] >= 1, str(res["matched"]))
check("结果带归档编号", res["hits"][0]["id"] == aid_x, res["hits"][0]["id"])
check("结果带行号", isinstance(res["hits"][0]["line"], int))
check("结果带角色", res["hits"][0]["role"] in ("user", "assistant", "tool"))
check("结果带片段", "logging" in res["hits"][0]["snippet"])
check("扫描了全部归档", res["archives_scanned"] >= 2, str(res["archives_scanned"]))

res2 = recall_tool.search(archive_dir, "pandas")
check("未指定 id 时检索所有归档", res2["hits"][0]["id"] == "20261023-090000", str(res2["hits"][:1]))
res3 = recall_tool.search(archive_dir, "pandas", archive_id=aid_x)
check("指定 id 时只查该归档", res3["matched"] == 0, str(res3["matched"]))
res4 = recall_tool.search(archive_dir, "logging", archive_id=aid_x)
check("指定 id 能查到", res4["matched"] >= 1, str(res4["matched"]))
res5 = recall_tool.search(archive_dir, "完全不存在的词汇zzz")
check("无命中给提示", res5["matched"] == 0 and "没有匹配" in res5.get("message", ""), str(res5)[:80])
res6 = recall_tool.search(archive_dir, "main.py logging")
check("多关键词命中更多词的排前面", res6["hits"][0]["score"] >= len(res6["hits"][0]["matched"]) * 10)
res7 = recall_tool.search(archive_dir, "logging", limit=1)
check("limit 生效", len(res7["hits"]) == 1, str(len(res7["hits"])))
res8 = recall_tool.search(TMP / "no_such_dir", "x")
check("无归档目录时明确说明", res8["hits"] == [] and "还没有任何" in res8.get("message", ""))
res9 = recall_tool.search(archive_dir, "   ")
check("空关键词报错", "error" in res9)

out = recall_tool.execute_tool({"text": "logging"}, archive_dir)
check("execute_tool 返回 JSON", isinstance(json.loads(out).get("hits"), list))
out2 = recall_tool.execute_tool({}, archive_dir)
check("缺 text 时返回错误", "error" in json.loads(out2))
check("schema 必需参数只有 text", recall_tool.TOOL_SCHEMA["function"]["parameters"]["required"] == ["text"])
check("schema 声明了 id 参数", "id" in recall_tool.TOOL_SCHEMA["function"]["parameters"]["properties"])

print("\n⑩ 与 xAgent 集成")
try:
    import xagent
    names = [s["function"]["name"] for s in xagent.TOOL_SCHEMAS]
    check("recallContext 已注册进工具声明", "recallContext" in names, str(names))
    xagent.CONTEXT.archive_dir = archive_dir          # 指向临时归档目录
    out3 = json.loads(xagent.dispatch_tool("recallContext", {"text": "logging"}))
    check("dispatch_tool 能检索到归档", out3.get("matched", 0) >= 1, str(out3)[:80])
    ctx3 = xagent.CONTEXT
    ctx3.note_usage({"prompt_tokens": ctx3.window})
    ctx3.update_blocked(ctx3.window)
    answer, hist = xagent.run_agent("随便问点什么", [], verbose=False, ctx=ctx3)
    check("达阈值后拒绝普通提示词", "/compact" in answer and hist == [], answer[:60])
except Exception as e:                                  # noqa: BLE001
    check("xAgent 集成可用", False, f"{type(e).__name__}: {e}")

print("\n⑪ 压缩日志：记清楚压了什么")
hist_log = [
    {"role": "user", "content": "把 main.py 的日志改成 logging 模块，别再用 print"},
    {"role": "assistant", "content": None,
     "tool_calls": [{"id": "c1", "type": "function",
                     "function": {"name": "RunCli", "arguments": '{"command":"ls"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "main.py\ncontext_manager.py"},
    {"role": "assistant", "content": "已改成 logging。"},
    {"role": "user", "content": "再补一个 recallContext 工具的说明"},
    {"role": "assistant", "content": "好的，已补。"},
]
desc = cm.describe_history(hist_log)
check("统计总条数", desc["total"] == 6, str(desc["total"]))
check("角色分布 user=2", desc["roles"]["user"] == 2, str(desc["roles"]))
check("角色分布 assistant=3", desc["roles"]["assistant"] == 3, str(desc["roles"]))
check("角色分布 tool=1", desc["roles"]["tool"] == 1, str(desc["roles"]))
check("提取用户诉求 2 条", len(desc["topics"]) == 2, str(desc["topics"]))
check("诉求内容被截断压成一行", desc["topics"][0].startswith("把 main.py 的日志改成 logging"), desc["topics"][0])
check("识别出用过的工具", desc["tools"] == ["RunCli"], str(desc["tools"]))
check("Token 估计大于 0", desc["tokens"] > 0, str(desc["tokens"]))

outline = cm.summary_outline("# 工作摘要\n\n## 一、用户目标\n正文\n## 二、已完成\n### 细节\n")
check("摘要目录抽取标题", outline == ["工作摘要", "一、用户目标", "二、已完成", "细节"], str(outline))

ctx_log = ContextManager(project_root=TMP, model="qwen-plus", archive_dir=TMP / "logctx")
new_hist2, info2 = ctx_log.compact(hist_log, fake_chat, verbose=False, printer=lambda *_: None)
check("info 里带 before 统计", info2["before"]["total"] == 6, str(info2.get("before")))
check("info 里带摘要目录", "工作摘要" in info2["outline"], str(info2["outline"]))
check("info 里带日志路径", info2["log_path"].endswith("compact.log"), info2["log_path"])
check("日志文件已落盘", Path(info2["log_path"]).is_file())

log_text = Path(info2["log_path"]).read_text(encoding="utf-8")
check("日志含归档编号", info2["id"] in log_text)
check("日志含消息条数与角色分布", "6 条" in log_text and "user 2" in log_text, log_text[:200])
check("日志含用户诉求原文", "把 main.py 的日志改成 logging" in log_text)
check("日志含涉及工具", "RunCli" in log_text)
check("日志含摘要结构", "工作摘要" in log_text)
check("日志含压缩前后 Token", "压缩" in log_text and "→" in log_text)

block_lines = cm.describe_block(info2)
joined = "\n".join(block_lines)
check("describe_block 有标题", block_lines[0].startswith("📦"), block_lines[0])
check("清单含原始消息", "原始消息" in joined)
check("清单含用户诉求", "用户诉求" in joined)
check("清单含归档文件", "归档文件" in joined)
check("清单含压缩日志", "压缩日志" in joined)

# 再压一次，日志应追加而不是覆盖
new_hist3, info3 = ctx_log.compact(new_hist2 * 2, fake_chat, verbose=False, printer=lambda *_: None)
log_text2 = Path(info3["log_path"]).read_text(encoding="utf-8")
check("第二次压缩追加日志（两条记录都在）",
      log_text2.count("=" * 62) == 2 and info2["id"] in log_text2 and info3["id"] in log_text2,
      f"分隔线 {log_text2.count('=' * 62)} 条")
recent = cm.read_compact_log(Path(info3["log_path"]), blocks=1)
check("read_compact_log 只取最近 1 次", info3["id"] in recent and info2["id"] not in recent, recent[:120])

# 摘要消息不该被当成新诉求
desc2 = cm.describe_history(new_hist2)
check("压缩摘要不算用户诉求", desc2["topics"] == [], str(desc2["topics"]))

print()
print(f"通过 {passed} 项，失败 {failed} 项")
sys.exit(0 if failed == 0 else 1)
