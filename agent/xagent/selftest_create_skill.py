# -*- coding: utf-8 -*-
"""createSkill / fileOps 自测（不调用 LLM，纯本地校验）。

覆盖实验要求第 131–139 行：
    创建成功、目录名 = 英文 slug、Frontmatter 规范化（缺 name 补写 / name 不一致改写）、
    非法名称拒绝、已存在拒绝覆盖、缺少 description/正文拒绝、缺 Frontmatter 拒绝、
    创建后自动注册、fileOps 建目录/写文件/列目录、路径越界拒绝。

用法：
    python selftest_create_skill.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_skill_tool import execute_tool as create_skill      # noqa: E402
from file_ops_tool import execute_tool as file_ops             # noqa: E402
from skills import SkillRegistry                               # noqa: E402

PASS, FAIL = [], []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"{'✅' if ok else '❌'} {label}" + (f" —— {detail}" if detail else ""))


def j(raw: str) -> dict:
    return json.loads(raw)


GOOD_CONTEXT = (
    "---\n"
    "name: weekly-report\n"
    "description: 生成周报模板，用户要求写周报时使用\n"
    "---\n"
    "1. 先确认部门与姓名；\n"
    "2. 按「本周完成 / 下周计划 / 风险」三段输出。\n"
)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="xagent_create_"))
    root = tmp / ".agents" / "skills"
    root.mkdir(parents=True)
    reg = SkillRegistry(root=root, project_root=tmp, source="临时测试目录")
    reg.scan()

    try:
        section("① 正常创建")
        r = j(create_skill(reg, {"name": "weekly-report", "skillContext": GOOD_CONTEXT}))
        target = root / "weekly-report" / "SKILL.md"
        check("返回 ok", r.get("ok") is True, str(r.get("error", ""))[:60])
        check("目录按 name 创建", target.is_file(), str(target))
        text = target.read_text(encoding="utf-8")
        check("SKILL.md 内容完整写入", "下周计划" in text and text.startswith("---"))
        check("创建后自动注册", r.get("registered") is True and reg.get("weekly-report") is not None)
        check("注册总数正确", r.get("skills_total") == 1, str(r.get("skills_total")))

        section("② 已存在时拒绝覆盖")
        before = target.read_text(encoding="utf-8")
        r = j(create_skill(reg, {"name": "weekly-report", "skillContext": GOOD_CONTEXT}))
        check("返回错误而非覆盖", "已存在" in r.get("error", ""), r.get("error", "")[:50])
        check("原文件一字未改", target.read_text(encoding="utf-8") == before)
        check("提示已存在的文件清单", "SKILL.md" in r.get("existing_files", []))

        section("③ 名称规范校验")
        for bad in ["写通知", "Weekly-Report", "weekly report", "-report", "report-", "a--b", "report_v2"]:
            r = j(create_skill(reg, {"name": bad, "skillContext": GOOD_CONTEXT}))
            check(f"拒绝非法名称「{bad}」", "不可用" in r.get("error", ""), r.get("error", "")[:40])
        check("未产生任何目录",
              not any(p.is_dir() for p in root.iterdir() if p.name != "weekly-report"))

        section("④ Frontmatter 规范化")
        no_name = "---\ndescription: 缺少 name 的技能\n---\n正文规则\n"
        r = j(create_skill(reg, {"name": "auto-name", "skillContext": no_name}))
        body = (root / "auto-name" / "SKILL.md").read_text(encoding="utf-8")
        check("缺 name 时按参数补写", r.get("ok") and "name: auto-name" in body, str(r.get("notes")))

        mismatch = "---\nname: old-name\ndescription: 名称不一致\n---\n正文\n"
        r = j(create_skill(reg, {"name": "new-name", "skillContext": mismatch}))
        body = (root / "new-name" / "SKILL.md").read_text(encoding="utf-8")
        check("name 不一致时改写为参数名", r.get("ok") and "name: new-name" in body, str(r.get("notes")))
        check("改写有说明返回", bool(r.get("notes")))

        section("⑤ 内容不合格拒绝")
        no_desc = "---\nname: no-desc\n---\n正文\n"
        check("缺 description 拒绝",
              "description" in j(create_skill(reg, {"name": "no-desc", "skillContext": no_desc})).get("error", ""))
        no_body = "---\nname: no-body\ndescription: 只有头没有正文\n---\n"
        check("缺正文拒绝",
              "正文" in j(create_skill(reg, {"name": "no-body", "skillContext": no_body})).get("error", ""))
        no_fm = "这是一段没有 Frontmatter 的纯文本\n"
        err = j(create_skill(reg, {"name": "no-fm", "skillContext": no_fm})).get("error", "")
        check("缺 Frontmatter 拒绝", "Frontmatter" in err, err[:40])
        check("缺 name 参数报错", "name" in j(create_skill(reg, {"name": "", "skillContext": GOOD_CONTEXT})).get("error", ""))

        section("⑥ fileOps：辅助目录与文件")
        r = j(file_ops(root, {"action": "make_dir", "path": "weekly-report/references"}))
        check("创建 references 目录", r.get("ok") and (root / "weekly-report" / "references").is_dir())
        r = j(file_ops(root, {
            "action": "write_file",
            "path": "weekly-report/references/template.md",
            "content": "# 周报模板\n\n## 本周完成\n",
        }))
        check("写入辅助文件", r.get("ok") and (root / "weekly-report" / "references" / "template.md").is_file(),
              str(r.get("bytes")))
        r = j(file_ops(root, {"action": "list_files", "path": "weekly-report"}))
        names = [e["name"] for e in r.get("entries", [])]
        check("列目录看到 SKILL.md 与 references", "SKILL.md" in names and "references" in names, str(names))
        r = j(file_ops(root, {
            "action": "write_file",
            "path": "weekly-report/scripts/gen.py",
            "content": "print('hi')\n",
        }))
        check("父目录自动补建", r.get("ok") and (root / "weekly-report" / "scripts" / "gen.py").is_file())

        section("⑦ fileOps：路径越界拒绝")
        r = j(file_ops(root, {"action": "write_file", "path": "../outside.txt", "content": "x"}))
        check("相对路径越界拒绝", "拒绝" in r.get("error", ""), r.get("error", "")[:50])
        r = j(file_ops(root, {"action": "make_dir", "path": str(tmp / "evil")}))
        check("绝对路径越界拒绝", "拒绝" in r.get("error", ""), r.get("error", "")[:50])
        check("越界未创建任何文件",
              not (tmp / "outside.txt").exists() and not (tmp / "evil").exists())
        r = j(file_ops(root, {"action": "explode", "path": "."}))
        check("未知 action 报错", "未知 action" in r.get("error", ""))

        section("⑧ 热加载后的 loadSkill")
        from load_skill_tool import execute_tool as load_skill
        r = j(load_skill(reg, {"name": "weekly-report"}))
        check("新技能可被 loadSkill 读取", "下周计划" in r.get("content", ""), r.get("file", ""))
        r = j(load_skill(reg, {"name": "weekly-report", "filename": "references/template.md"}))
        check("辅助文件可被 loadSkill 读取", "周报模板" in r.get("content", ""), r.get("file", ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 52)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
