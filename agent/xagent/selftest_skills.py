# -*- coding: utf-8 -*-
"""Skill 动态加载机制自测（不调用 LLM，纯本地校验）。

覆盖实验要求中的每一条：
    发现与注册 / 只加载 name+description / Prompt 注入 /
    loadSkill 只传 name / name+filename / 只给文件名递归搜索 /
    同名多文件返回候选 / 目录内限制（越界拒绝）/ 缺字段跳过。

用法：
    python selftest_skills.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_skill_tool import execute_tool          # noqa: E402
from skills import SkillRegistry, parse_frontmatter, read_frontmatter_head  # noqa: E402

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "✅" if condition else "❌"
    print(f"{mark} {label}" + (f" —— {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def load(reg: SkillRegistry, **kwargs) -> dict:
    return json.loads(execute_tool(reg, kwargs))


# --------------------------------------------------------------------------- #
def test_real_registry() -> None:
    reg = SkillRegistry.discover()
    section("① 发现与注册（真实目录）")
    print(f"   技能目录：{reg.root}")
    print(f"   来源：{reg.source}")
    check("注册表非空", len(reg.skills) > 0, f"{len(reg.skills)} 个技能")
    check("解析出 name/description", all(s.name and s.description for s in reg.skills.values()))
    check("跳过缺 SKILL.md 的目录", any("SKILL.md" in r for _, r in reg.skipped),
          str(reg.skipped))

    section("② System Prompt 注入")
    prompt = reg.prompt_section()
    check("包含技能清单标题", "You have access to the following skills" in prompt)
    check("包含 loadSkill 使用说明", "`loadSkill`" in prompt)
    check("只注入 name+description（不含正文）",
          all(s.name in prompt for s in reg.skills.values())
          and "Frontmatter" not in prompt.split("Use the `loadSkill`")[0][:2000])

    notice = reg.get("撰写通知")
    if notice:
        head = read_frontmatter_head(notice.skill_file)
        full = notice.skill_file.read_text(encoding="utf-8", errors="replace")
        body_marker = "标题必须加入部门名称"          # 只出现在正文里的标记
        check("初始化只读 Frontmatter 头（不读正文）",
              body_marker not in head and body_marker in full,
              f"头部 {len(head)} 字符 / 全文 {len(full)} 字符")

    if "撰写通知" not in reg.names():
        print("\n⚠️ 未找到「撰写通知」技能，跳过后续用例")
        return

    section("③ loadSkill：只传 name")
    r = load(reg, name="撰写通知")
    check("返回 SKILL.md 全文", r.get("file", "").lower() == "skill.md", r.get("file", ""))
    check("正文含规则原文", "标题必须加入部门名称" in r.get("content", ""))

    section("④ loadSkill：name + filename（相对路径）")
    skill = reg.get("horoscope-daily")
    if skill:
        rel = next((p.relative_to(skill.directory).as_posix()
                    for p in skill.directory.rglob("*.md")
                    if p.name != "SKILL.md"), None)
        if rel:
            r = load(reg, name="horoscope-daily", filename=rel)
            check("读取附加文件成功", r.get("file") == rel, r.get("file", ""))
            check("不再重复返回 SKILL.md", r.get("content") != reg.read_skill_file(skill))
            bare = Path(rel).name
            r2 = load(reg, name="horoscope-daily", filename=bare)
            check("只给文件名可递归命中", r2.get("file") == rel, r2.get("file") or r2.get("error", ""))

    section("⑤ 目录内限制（越界拒绝）")
    out = load(reg, name="撰写通知", filename="../../../../config.ini")
    check("越界路径被拒绝", "拒绝读取" in out.get("error", ""), out.get("error", "")[:60])
    out2 = load(reg, name="撰写通知", filename="skills.py")   # 项目内但在 Skill 目录外
    check("项目内但越界同样拒绝", "error" in out2, out2.get("error", "")[:60])

    section("⑥ 异常分支")
    out = load(reg, name="不存在的技能")
    check("未知技能返回可用列表", "available_skills" in out, str(out.get("available_skills")))
    out = load(reg, name="撰写通知", filename="no_such_file.md")
    check("文件不存在给出错误", "找不到" in out.get("error", ""), out.get("error", "")[:60])
    out = load(reg, name="notice")     # 用目录名也能命中
    check("兼容目录名调用", out.get("skill") == "撰写通知", out.get("skill", ""))


# --------------------------------------------------------------------------- #
def test_temp_registry() -> None:
    section("⑦ 临时技能目录（缺字段跳过 / 同名多文件候选 / 环境变量优先）")
    tmp = Path(tempfile.mkdtemp(prefix="xagent_skills_"))
    root = tmp / ".agents" / "skills"
    try:
        (root / "good").mkdir(parents=True)
        (root / "good" / "SKILL.md").write_text(
            '---\nname: demo-skill\ndescription: "演示用技能"\n---\n正文内容\n',
            encoding="utf-8")
        (root / "bad").mkdir()
        (root / "bad" / "SKILL.md").write_text(
            '---\ndescription: 只有描述没有 name\n---\n', encoding="utf-8")
        (root / "dup").mkdir()
        (root / "dup" / "SKILL.md").write_text(
            '---\nname: dup-skill\ndescription: 同名文件测试\n---\n', encoding="utf-8")
        (root / "dup" / "a").mkdir()
        (root / "dup" / "b").mkdir()
        (root / "dup" / "a" / "x.md").write_text("A 版本", encoding="utf-8")
        (root / "dup" / "b" / "x.md").write_text("B 版本", encoding="utf-8")

        old = os.environ.get("XAGENT_SKILLS_DIR")
        os.environ["XAGENT_SKILLS_DIR"] = str(root)
        reg = SkillRegistry.discover()
        check("环境变量优先生效", reg.root == root.resolve(), str(reg.root))
        check("缺 name 的目录被跳过", any(n == "bad" for n, _ in reg.skipped), str(reg.skipped))
        check("合法技能注册成功", "demo-skill" in reg.names())

        out = load(reg, name="dup-skill", filename="x.md")
        check("同名文件返回候选而非乱读",
              len(out.get("candidates", [])) == 2, str(out.get("candidates")))
        out = load(reg, name="dup-skill", filename="b/x.md")
        check("候选之一可精确读取", out.get("content") == "B 版本", out.get("file", ""))
    finally:
        if old is None:
            os.environ.pop("XAGENT_SKILLS_DIR", None)
        else:
            os.environ["XAGENT_SKILLS_DIR"] = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_frontmatter() -> None:
    section("⑧ Frontmatter 解析")
    m = parse_frontmatter('---\nname: "a b"\ndescription: |\n  第一行\n  第二行\n---\n正文')
    check("双引号去除", m.get("name") == "a b", m.get("name", ""))
    check("块标量保留换行", m.get("description") == "第一行\n第二行", repr(m.get("description")))
    m2 = parse_frontmatter('---\nname: x\ndescription: >\n  折行\n  文本\n---\n')
    check("折叠标量合成一行", m2.get("description") == "折行 文本", repr(m2.get("description")))
    check("无 frontmatter 返回空", parse_frontmatter("正文没有头部") == {})


if __name__ == "__main__":
    test_real_registry()
    test_temp_registry()
    test_frontmatter()
    print(f"\n{'='*52}\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    sys.exit(0 if not FAIL else 1)
