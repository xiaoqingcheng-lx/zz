# -*- coding: utf-8 -*-
"""createSkill —— 让 Agent 按用户的自然语言要求创建新的 Skill。

对应实验要求（第 131–139 行）：
1. 工具接收两个参数：``name``（Skill 名称）、``skillContext``（要写入 SKILL.md 的完整内容）；
2. 在当前项目生效的 ``.agents/skills/`` 下创建与 name 对应的**英文子目录**，
   并在其中生成 ``SKILL.md``，写入 skillContext；
3. 生成的 SKILL.md 必须符合 Agent Skills 规范：YAML Frontmatter + name + description + 正文；
   Skill 名称统一为「小写字母、数字、连字符」；
4. 目标 Skill 已存在时返回明确提示，**绝不覆盖**原有内容；
5. 需要 references/、scripts/ 等辅助目录或文件时，提示 LLM 继续调用 fileOps 工具。

安全边界：name 先过 slug 正则（不含 ``/``、``.``、``:``），因此目录只能落在 skills 根下，
不存在 ``../`` 逃逸的可能。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from skills import SKILL_FILE, SkillRegistry, parse_frontmatter

# 小写字母、数字、连字符；不允许首尾连字符、不允许连续连字符
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_CONTEXT_CHARS = 200_000
MAX_NAME_CHARS = 64

TEMPLATE = (
    "---\n"
    "name: my-skill\n"
    "description: 一句话说明这个技能做什么、什么时候该用它\n"
    "---\n"
    "这里写具体的操作规则/步骤，可以分条列出。\n"
)

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "createSkill",
        "description": (
            "创建一个新的 Skill（技能）。当用户要求「新建/生成/保存一个技能」时调用。"
            "工具会在当前项目的 .agents/skills/ 下创建与 name 同名的英文子目录，"
            "并写入 SKILL.md。skillContext 必须是完整的 SKILL.md 内容，"
            "包含 YAML Frontmatter（name、description）和正文规则。"
            "如果还需要 references/、scripts/ 等辅助目录或文件，创建成功后再调用 fileOps 工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Skill 名称，也是目录名。只能用小写字母、数字、连字符，"
                        "例如 write-notice、weekly-report；中文或大写会被拒绝"
                    ),
                },
                "skillContext": {
                    "type": "string",
                    "description": (
                        "要写入 SKILL.md 的完整内容：以 --- 包裹的 YAML Frontmatter"
                        "（含 name、description）加正文规则说明"
                    ),
                },
            },
            "required": ["name", "skillContext"],
        },
    },
}


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _validate_name(name: str) -> str | None:
    """返回错误说明；合法时返回 None。"""
    if len(name) > MAX_NAME_CHARS:
        return f"名称过长（{len(name)} 字符，上限 {MAX_NAME_CHARS}）"
    if not NAME_PATTERN.match(name):
        return (
            "名称不符合规范：只能由小写字母、数字、连字符组成，"
            "且不能以连字符开头/结尾或出现连续连字符（例如 write-notice、pdf-report2）"
        )
    return None


def _rewrite_name(text: str, name: str) -> str:
    """把 Frontmatter 里的 name 改写成参数值，保证目录名与 name 一致。"""
    lines = text.splitlines(keepends=True)
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:                      # 正常情况下不会走到这里（前面已校验）
        return text
    for i in range(1, end):
        if re.match(r"^\s*name\s*:", lines[i]):
            newline = "\n" if lines[i].endswith("\n") else ""
            lines[i] = f"name: {name}{newline}"
            return "".join(lines)
    lines.insert(1, f"name: {name}\n")
    return "".join(lines)


def _prepare(name: str, context: str) -> tuple[str | None, str | None, list[str]]:
    """校验并规范化 skillContext，返回 (最终文本, 错误, 说明列表)。"""
    text = context.strip("\ufeff").replace("\r\n", "\n")
    if not text.startswith("---"):
        return None, (
            "skillContext 必须以 YAML Frontmatter 开头（第一行为 ---），"
            f"否则生成的 SKILL.md 不符合 Agent Skills 规范。请按此模板重新调用：\n{TEMPLATE}"
        ), []
    if len(text) > MAX_CONTEXT_CHARS:
        return None, f"skillContext 过长（{len(text)} 字符，上限 {MAX_CONTEXT_CHARS}）", []

    meta = parse_frontmatter(text)
    if not meta:
        return None, "Frontmatter 解析失败：请检查是否以 --- 开头、以 --- 结束", []
    if not meta.get("description"):
        return None, (
            "Frontmatter 缺少必需的 description 字段。"
            "description 要说明「这个技能做什么、什么时候用它」，请补充后重新调用。"
        ), []
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    body = "\n".join(lines[end + 1:]) if end is not None else ""
    if not body.strip():
        return None, "缺少正文内容：Frontmatter 之后需要写入技能的操作规则/步骤", []

    notes: list[str] = []
    if (meta.get("name") or "").strip() != name:
        if meta.get("name"):
            notes.append(f"Frontmatter 中的 name「{meta['name']}」已改写为参数名「{name}」，保持目录与 name 一致")
        else:
            notes.append(f"Frontmatter 缺少 name，已按参数补写为「{name}」")
        text = _rewrite_name(text, name)
    return text, None, notes


def execute_tool(registry: SkillRegistry, arguments: dict) -> str:
    """执行 createSkill，返回 JSON 字符串作为 role=tool 消息。"""
    name = str(arguments.get("name", "") or "").strip()
    context = str(arguments.get("skillContext", "") or "")

    if not name:
        return _dump({"error": "缺少必填参数 name"})
    problem = _validate_name(name)
    if problem:
        return _dump({
            "error": f"Skill 名称「{name}」不可用：{problem}",
            "hint": "请把名称改成英文 slug 后重新调用，例如 write-notice、weekly-report",
        })

    target_dir = registry.root / name
    skill_file = target_dir / SKILL_FILE
    if target_dir.exists() or skill_file.exists():
        existing = sorted(p.name for p in target_dir.iterdir()) if target_dir.is_dir() else []
        return _dump({
            "error": f"Skill「{name}」已存在，已停止操作以避免覆盖原有内容",
            "path": str(target_dir),
            "existing_files": existing,
            "hint": "如果要修改它，请用 fileOps 工具直接编辑；如果要新建，请换一个名称",
        })

    text, error, notes = _prepare(name, context)
    if error:
        return _dump({"error": error, "skill": name})

    try:
        target_dir.mkdir(parents=True)
        skill_file.write_text(text, encoding="utf-8")
    except OSError as e:
        shutil.rmtree(target_dir, ignore_errors=True)     # 失败不留半成品目录
        return _dump({"error": f"写入 SKILL.md 失败：{e}", "skill": name})

    # 热加载：立刻重新扫描，同一轮对话后续即可 loadSkill 到它
    registry.scan()
    registered = registry.get(name) is not None
    payload = {
        "ok": True,
        "skill": name,
        "path": str(skill_file),
        "registered": registered,
        "skills_total": len(registry.skills),
        "next": (
            "SKILL.md 已创建并注册。如需 references/、scripts/ 等辅助目录或文件，"
            "请继续调用 fileOps 工具在 " + str(target_dir) + " 下创建。"
        ),
    }
    if notes:
        payload["notes"] = notes
    return _dump(payload)
