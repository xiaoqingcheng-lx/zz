# -*- coding: utf-8 -*-
"""officeCli 工具自测（真实调用 officecli，不调 LLM）。

覆盖：可执行文件自动定位（含 env 覆盖与缓存失效）、参数校验、
版本/帮助、创建 docx、写段落、导出文本、校验、错误分支。

用法：
    python selftest_office_cli.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import office_cli_tool                                   # noqa: E402
from office_cli_tool import execute_tool, find_officecli  # noqa: E402
from skills import SkillRegistry                          # noqa: E402

PASS, FAIL = [], []
SKILLS_ROOT = Path(r"D:\大语言模型\agent\office\.agents\skills")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"{'✅' if ok else '❌'} {label}" + (f" —— {detail}" if detail else ""))


def call(*args, **kwargs) -> dict:
    return json.loads(execute_tool({"args": list(args), **kwargs}, [SKILLS_ROOT]))


def main() -> None:
    section("① 可执行文件定位")
    exe = find_officecli([SKILLS_ROOT])
    check("能找到 officecli", exe is not None and exe.is_file(), str(exe))
    if exe is None:
        print("无法继续，退出")
        sys.exit(1)
    check("位于技能目录内", SKILLS_ROOT.resolve() in exe.resolve().parents, str(exe.parent.name))
    second = find_officecli([SKILLS_ROOT])
    check("命中缓存（同一文件）", second == exe)

    section("② 基础命令")
    r = call("--version")
    check("--version 退出码 0", r.get("exit_code") == 0, r.get("stdout", "").strip() or r.get("error", ""))
    check("返回版本号", any(c.isdigit() for c in r.get("stdout", "")), r.get("stdout", "").strip())

    r = call("help", "docx", "paragraph")
    check("help 查到 docx paragraph", r.get("exit_code") == 0 and "paragraph" in r.get("stdout", "").lower(),
          str(r.get("exit_code")))

    section("③ 完整流程：新建 docx → 写段落 → 导出文本 → 校验")
    tmp = Path(tempfile.mkdtemp(prefix="officecli_test_"))
    doc = tmp / "测试文档.docx"
    try:
        r = call("create", str(doc))
        check("create 成功", r.get("exit_code") == 0 and doc.is_file(), r.get("stderr", "")[:80])

        r = call("add", str(doc), "/body", "--type", "paragraph",
                 "--prop", "text=这是一段由 officeCli 工具写入的文字",
                 "--prop", "style=Heading1")
        check("add 段落成功", r.get("exit_code") == 0, r.get("stderr", "")[:80])

        r = call("view", str(doc), "text")
        out = r.get("stdout", "")
        check("view text 读回中文内容", "officeCli 工具写入的文字" in out, out.strip()[:60])

        r = call("validate", str(doc))
        check("validate 通过", r.get("exit_code") == 0, (r.get("stderr") or r.get("stdout", ""))[:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    section("④ 异常分支")
    r = json.loads(execute_tool({"args": []}, [SKILLS_ROOT]))
    check("空 args 报错", "缺少必填参数" in r.get("error", ""), r.get("error", "")[:40])

    r = call("view", "C:/不存在的文件_abc123.docx", "text")
    check("文件不存在返回非 0", r.get("exit_code") not in (None, 0), str(r.get("exit_code")))
    check("非 0 时给出排查提示", "hint" in r)

    old = os.environ.get("OFFICECLI_EXE")
    os.environ["OFFICECLI_EXE"] = str(exe)          # 有效 env 应被优先采用
    office_cli_tool._EXE_CACHE = None
    r = call("--version")
    check("env 有效时优先使用", r.get("exit_code") == 0 and Path(r.get("exe", "")) == exe,
          r.get("exe", ""))

    os.environ["OFFICECLI_EXE"] = "C:/no/such/officecli.exe"   # 无效 env → 回退自动定位
    office_cli_tool._EXE_CACHE = None
    r = call("--version")
    check("env 无效时回退自动定位", r.get("exit_code") == 0 and Path(r.get("exe", "")) == exe,
          r.get("exe", ""))

    os.environ["OFFICECLI_EXE"] = "C:/no/such/officecli.exe"
    office_cli_tool._EXE_CACHE = None
    r = json.loads(office_cli_tool.execute_tool({"args": ["--version"]}, [Path("C:/no/such/dir")]))
    check("找不到时返回明确错误", "未找到" in r.get("error", ""), r.get("error", "")[:50])

    if old is None:
        os.environ.pop("OFFICECLI_EXE", None)
    else:
        os.environ["OFFICECLI_EXE"] = old

    office_cli_tool._EXE_CACHE = None
    r = call("--version")
    check("清缓存后可重新定位", r.get("exit_code") == 0, r.get("stdout", "").strip())

    section("⑤ 技能已注册且可加载")
    reg = SkillRegistry.discover()
    check("office-cli 出现在注册表", "office-cli" in reg.names(), str(reg.names()))
    from load_skill_tool import execute_tool as load_skill
    r = json.loads(load_skill(reg, {"name": "office-cli"}))
    check("SKILL.md 可加载", "officeCli" in r.get("content", ""), r.get("file", ""))

    print("\n" + "=" * 52)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
