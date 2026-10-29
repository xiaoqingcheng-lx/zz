# -*- coding: utf-8 -*-
"""loadSkill —— xAgent 的 Function Calling 工具：按需加载 Skill 正文/附加文件。

设计要点（对应实验要求）：
1. 参数只有两个：
   - ``name``（必需）：Skill 名称（Frontmatter 里的 name，兼容目录名）；
   - ``filename``（可选）：要加载的文件路径或文件名。
2. 只给 ``name`` → 返回该 Skill 的 ``SKILL.md`` 全文。
3. ``name`` + ``filename`` → 只读取该文件，**不重复加载 SKILL.md**。
4. filename 兼容 Skill 目录相对路径、项目相对路径、绝对路径；先精确匹配，
   只给文件名时递归搜索，命中多个则返回候选列表交给 LLM 决定。
5. 读取范围限制在该 Skill 目录内，越界（如 ``../../_secret.py``）直接拒绝。
6. Skill 正文**只经由此工具进入对话上下文**，初始化阶段不预加载。
"""
from __future__ import annotations

import json
from pathlib import Path

from skills import SkillRegistry

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "loadSkill",
        "description": (
            "加载某个技能（Skill）的完整说明或附加文件。"
            "只传 name 时返回该技能的 SKILL.md 全文；"
            "同时传 filename 时只读取该文件（例如 references/xxx.md、scripts/xxx.py），"
            "适合在读完 SKILL.md 后按需读取它引用的资料。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "技能名称，必须与 System Prompt 中列出的名称一致",
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "可选。要加载的文件路径或文件名，支持该技能目录内的相对路径、"
                        "项目相对路径、绝对路径；只给文件名时会递归搜索"
                    ),
                },
            },
            "required": ["name"],
        },
    },
}


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def execute_tool(registry: SkillRegistry, arguments: dict) -> str:
    """执行 loadSkill，返回 JSON 字符串作为 role=tool 消息。"""
    name = str(arguments.get("name", "")).strip()
    filename = str(arguments.get("filename", "") or "").strip()

    if not name:
        return _dump(
            {
                "error": "缺少必填参数 name",
                "available_skills": registry.names(),
            }
        )

    skill = registry.get(name)
    if skill is None:
        return _dump(
            {
                "error": f"未找到技能「{name}」",
                "available_skills": registry.names(),
                "hint": "请使用 System Prompt 中列出的技能名称之一",
            }
        )

    # ---- 情形一：只给 name → 返回 SKILL.md 全文 ----
    if not filename:
        try:
            content = registry.read_skill_file(skill)
        except OSError as e:
            return _dump({"error": f"读取 {skill.skill_file.name} 失败：{e}", "skill": skill.name})
        return _dump(
            {
                "skill": skill.name,
                "file": skill.skill_file.name,
                "content": content,
            }
        )

    # ---- 情形二：给了 filename → 只读该文件，不重复加载 SKILL.md ----
    res = registry.resolve_filename(skill, filename)
    if res.error:
        return _dump({"skill": skill.name, "error": res.error, "requested": filename})
    if res.candidates:
        return _dump(
            {
                "skill": skill.name,
                "error": f"存在 {len(res.candidates)} 个匹配文件，请指定其中一个相对路径后重新调用",
                "candidates": res.candidates,
            }
        )

    try:
        content = registry.read_skill_file(skill, res.path)
    except OSError as e:
        return _dump({"skill": skill.name, "error": f"读取文件失败：{e}"})

    return _dump(
        {
            "skill": skill.name,
            "file": res.path.relative_to(skill.directory.resolve()).as_posix(),
            "content": content,
        }
    )


def describe(registry: SkillRegistry) -> str:
    """调试用：列出注册表概览。"""
    return registry.summary()


def _selftest() -> None:  # pragma: no cover - 手工调试入口
    reg = SkillRegistry.discover()
    print(reg.summary())
    print(reg.prompt_section())
    if reg.names():
        print(execute_tool(reg, {"name": reg.names()[0]})[:200])


if __name__ == "__main__":  # pragma: no cover
    _selftest()
