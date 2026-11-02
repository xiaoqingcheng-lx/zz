# -*- coding: utf-8 -*-
"""两条教学实践的验收自测（图片 142–151 行）。

教学实践 1：通过 createSkill 创建 miniEncryption 技能，
            用户说「加密保存」时把阿拉伯数字全部换成中文；
教学实践 2：通过 createSkill 创建 OfficeCLI 技能，
            让 Agent 能调用本地 officecli-win-x64.exe 读写 Word/Excel/PPT。

只读校验，不改任何文件。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_skill_tool import execute_tool as load_skill  # noqa: E402
from skills import SkillRegistry                        # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(desc: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(desc)
    print(f"[{'PASS' if ok else 'FAIL'}] {desc}" + (f"  · {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


reg = SkillRegistry.discover()

section("① miniEncryption 技能")
mini = reg.get("mini-encryption")
check("已注册 mini-encryption", mini is not None, str(reg.names()))
body = load_skill(reg, {"name": "mini-encryption"}) if mini else "{}"
mini_text = json.loads(body).get("content", "") if mini else ""
check("SKILL.md 可被 loadSkill 读取", bool(mini_text), json.loads(body).get("file", "") if mini else "")

if mini:
    check("frontmatter 有 description", bool(mini.description.strip()), mini.description[:40])
    check("目录名符合 slug 规范", re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", mini.name) is not None, mini.name)
    check("技能文件位于 .agents/skills 下",
          ".agents" in str(mini.directory).lower() and "skills" in str(mini.directory).lower(),
          str(mini.directory))

pairs = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
         "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}
missing = [f"{k}→{v}" for k, v in pairs.items() if v not in mini_text]
check("十个数字的映射齐全（零一二三四五六七八九）", not missing, "缺：" + "、".join(missing) if missing else "")

check("写明「逐位替换」而非数值换算", "逐位" in mini_text, "")
check("给出 123→一二三 类示例", "一二三" in mini_text, "")
check("强调小数点/负号原样保留", ("小数点" in mini_text or "3.14" in mini_text), "")
check("含交付前自检规则", "自检" in mini_text, "")

section("② OfficeCLI 技能")
office = reg.get("officecli")
check("已注册 officecli", office is not None, str(reg.names()))
office_json = json.loads(load_skill(reg, {"name": "officecli"})) if office else {}
office_text = office_json.get("content", "")
check("SKILL.md 可被 loadSkill 读取", bool(office_text), office_json.get("file", ""))

if office:
    check("frontmatter 有 description", bool(office.description.strip()), office.description[:40])
    check("目录名符合 slug 规范", re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", office.name) is not None, office.name)

check("提到 officecli-win-x64.exe", "officecli-win-x64.exe" in office_text, "")
check("提到参考文档 OfficeCli操作说明.md", "OfficeCli操作说明.md" in office_text, "")
check("说明调用入口是 officeCli 工具", "officeCli" in office_text, "")
check("覆盖 Word / Excel / PowerPoint 三种格式",
      all(k in office_text for k in ("Word", "Excel", "PPT")), "")
check("包含「先 help 再动手」规则", "help" in office_text, "")
check("包含改完复核（view text / validate）",
      ("view <文件> text" in office_text or "view" in office_text) and "validate" in office_text, "")

section("③ 环境：exe 与说明文档就位")
office_dir = Path(r"D:\大语言模型\agent\office")
check("office 目录下有 officecli-win-x64.exe", (office_dir / "officecli-win-x64.exe").is_file(), "")
check("office 目录下有 OfficeCli操作说明.md", (office_dir / "OfficeCli操作说明.md").is_file(), "")

from office_cli_tool import find_officecli  # noqa: E402

import office_cli_tool                      # noqa: E402
office_cli_tool._EXE_CACHE = None
exe = find_officecli([reg.root, office_dir])
check("工具能自动定位到 exe", exe is not None and exe.is_file(), str(exe))

print("\n" + "=" * 52)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "、".join(FAIL))
    sys.exit(1)
