# -*- coding: utf-8 -*-
"""Skill 发现与注册（Agent Skills 规范的最小实现）。

职责边界（严格对应实验要求）：
1. **发现**：以「程序启动时的工作目录」为项目根，向上逐级找 ``.agents/skills/``，
   扫描其中每个 Skill 子目录；子目录必须含 ``SKILL.md``，且其 YAML Frontmatter
   声明 ``name`` 与 ``description`` 两个必需字段。缺字段/缺少文件的目录会被跳过并记录原因。
2. **注册**：初始化阶段**只解析 name 与 description**，不读取 Skill 正文，
   避免一次性把所有技能全文塞进上下文。
3. **注入**：``prompt_section()`` 把注册结果渲染成一段 System Prompt 文本。
4. **文件解析**：``resolve_filename()`` 实现 loadSkill 的 filename 参数语义
   （精确路径优先 → Skill 目录相对 → 项目相对 → 递归同名搜索），
   并做**目录内限制**：任何解析结果都必须落在该 Skill 目录内。

本模块零 LLM / 零 UI 依赖，可被任何界面层复用。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SKILL_FILE = "SKILL.md"
REQUIRED_FIELDS = ("name", "description")

# 课程环境默认位置：xagent 与 office 是兄弟目录，技能放在 office 下
DEFAULT_SKILLS_DIR = (
    Path(__file__).resolve().parent.parent / "office" / ".agents" / "skills"
)

# 单个文件读取上限（防止异常大的文件撑爆上下文）
MAX_FILE_CHARS = 30000

# Frontmatter 只可能出现在文件开头；读到这里还没闭合就当没有（防止无闭合标记的
# 超长正文被整读进来，保证「初始化阶段不读取 Skill 完整正文」）
MAX_FRONTMATTER_LINES = 200


def read_frontmatter_head(path: Path) -> str:
    """只读取文件开头的 Frontmatter 块，**不读取正文**（对应实验要求 1）。

    从首行 ``---`` 开始逐行读，遇到闭合的 ``---`` 即停；
    一直没闭合则最多读 MAX_FRONTMATTER_LINES 行（parse_frontmatter 会判为缺字段）。
    """
    lines: list[str] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for _ in range(MAX_FRONTMATTER_LINES):
            line = f.readline()
            if not line:
                break
            lines.append(line)
            if len(lines) > 1 and line.strip() == "---":
                break
    return "".join(lines)


# --------------------------------------------------------------------------- #
# YAML Frontmatter 解析（只支持 name/description 这类简单标量 + 块标量 | >）
# --------------------------------------------------------------------------- #
def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].replace(value[0] * 2, value[0])
    return value


def parse_frontmatter(text: str) -> dict[str, str]:
    """解析 ``---`` 包裹的 YAML 头部，返回 {key: value}（扁平化）。

    支持：``key: value``、``key: "value"``、``key: |`` / ``key: >`` 块标量。
    解析失败一律返回空字典，由调用方判定为「缺必需字段」。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}

    body = lines[1:end]
    data: dict[str, str] = {}
    i = 0
    while i < len(body):
        raw = body[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^\s*([A-Za-z0-9_\u4e00-\u9fff\-]+)\s*:\s*(.*)$", raw)
        if not m:
            i += 1
            continue
        key, value = m.group(1).strip(), m.group(2).strip()

        # 块标量：后续缩进行都属于该 key
        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            block: list[str] = []
            i += 1
            while i < len(body) and (body[i].startswith((" ", "\t")) or not body[i].strip()):
                block.append(body[i].strip())
                i += 1
            sep = "\n" if value.startswith("|") else " "
            data[key] = sep.join(x for x in block if x)
            continue

        data[key] = _unquote(value)
        i += 1
    return data


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Skill:
    """一个已注册的 Skill（初始化时只持有元数据，不含正文）。"""

    name: str
    description: str
    directory: Path
    skill_file: Path

    @property
    def slug(self) -> str:
        return self.directory.name


@dataclass
class Resolution:
    """filename 解析结果。三者互斥：path / candidates / error。"""

    path: Path | None = None
    candidates: list[Path] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.path is not None


# --------------------------------------------------------------------------- #
# 技能目录定位
# --------------------------------------------------------------------------- #
def resolve_skills_root(start: Path | None = None) -> tuple[Path, str]:
    """按优先级定位 ``.agents/skills`` 目录，返回 (目录, 来源说明)。

    顺序：环境变量 → 工作目录及其父级 → 本文件所在目录 → 课程默认目录。
    """
    env = os.environ.get("XAGENT_SKILLS_DIR")
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p.resolve(), "环境变量 XAGENT_SKILLS_DIR"

    base = Path(start or os.getcwd()).resolve()
    for root in (base, *base.parents):
        cand = root / ".agents" / "skills"
        if cand.is_dir():
            return cand.resolve(), f"项目根 {root}"

    here = Path(__file__).resolve().parent
    cand = here / ".agents" / "skills"
    if cand.is_dir():
        return cand.resolve(), f"程序目录 {here}"

    if DEFAULT_SKILLS_DIR.is_dir():
        return DEFAULT_SKILLS_DIR.resolve(), "课程默认目录 agent/office"

    return (base / ".agents" / "skills").resolve(), "未找到技能目录"


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #
class SkillRegistry:
    """Skill 注册表：发现 → 注册（仅元数据）→ 渲染 Prompt 片段 → 解析文件。"""

    def __init__(self, root: Path, project_root: Path, source: str = "") -> None:
        self.root = Path(root)
        self.project_root = Path(project_root)
        self.source = source
        self.skills: dict[str, Skill] = {}          # key = name.lower()
        self.skipped: list[tuple[str, str]] = []    # (目录名, 跳过原因)

    # ---------------- 发现与注册 ----------------
    @classmethod
    def discover(cls, start: Path | None = None) -> "SkillRegistry":
        root, source = resolve_skills_root(start)
        project_root = Path(start or os.getcwd()).resolve()
        reg = cls(root, project_root, source)
        reg.scan()
        return reg

    def scan(self) -> None:
        self.skills.clear()
        self.skipped.clear()
        if not self.root.is_dir():
            return
        for sub in sorted(p for p in self.root.iterdir() if p.is_dir()):
            skill_file = self._find_skill_file(sub)
            if skill_file is None:
                self.skipped.append((sub.name, f"缺少 {SKILL_FILE}"))
                continue
            try:
                head = read_frontmatter_head(skill_file)   # 只读 Frontmatter 头部，不读正文
            except OSError as e:
                self.skipped.append((sub.name, f"读取失败：{e}"))
                continue
            meta = parse_frontmatter(head)
            missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
            if missing:
                self.skipped.append((sub.name, f"Frontmatter 缺少 {', '.join(missing)}"))
                continue
            skill = Skill(
                name=meta["name"].strip(),
                description=meta["description"].strip(),
                directory=sub,
                skill_file=skill_file,
            )
            key = skill.name.lower()
            if key in self.skills:                  # 同名冲突：保留先注册的，记录后者
                self.skipped.append((sub.name, f"name 与 {self.skills[key].slug} 重复"))
                continue
            self.skills[key] = skill

    @staticmethod
    def _find_skill_file(directory: Path) -> Path | None:
        """大小写不敏感地找 SKILL.md（兼容 skill.md 写法）。"""
        for f in directory.iterdir():
            if f.is_file() and f.name.lower() == SKILL_FILE.lower():
                return f
        return None

    # ---------------- 查询 ----------------
    def get(self, name: str) -> Skill | None:
        key = (name or "").strip().lower()
        if key in self.skills:
            return self.skills[key]
        for s in self.skills.values():              # 兼容用目录名调用
            if s.slug.lower() == key:
                return s
        return None

    def names(self) -> list[str]:
        return [s.name for s in self.skills.values()]

    # ---------------- 注入 System Prompt ----------------
    def prompt_section(self) -> str:
        """渲染成 System Prompt 片段；无技能时返回空串。"""
        if not self.skills:
            return ""
        lines = ["You have access to the following skills:"]
        for s in self.skills.values():
            lines.append(f"- `{s.name}`: {_one_line(s.description)}")
        lines.append(
            "Use the `loadSkill` tool to load the full instructions of a skill when needed. "
            "You can also load additional files referenced by a skill."
        )
        return "\n".join(lines)

    # ---------------- 读取正文 ----------------
    def read_skill_file(self, skill: Skill, path: Path | None = None) -> str:
        """读取 Skill 正文（默认 SKILL.md），超长时截断并标注。"""
        target = path or skill.skill_file
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_FILE_CHARS:
            return (
                text[:MAX_FILE_CHARS]
                + f"\n...[文件过长已截断：原始 {len(text)} 字符，仅保留前 {MAX_FILE_CHARS} 字符]"
            )
        return text

    # ---------------- filename 解析 ----------------
    def resolve_filename(self, skill: Skill, filename: str) -> Resolution:
        """把 LLM 给的 filename 解析成 Skill 目录内的真实文件。

        优先级：绝对路径 → Skill 目录相对 → 项目根相对 → 递归同名搜索。
        任何结果都必须落在 skill.directory 内，否则视为越界。
        """
        raw = (filename or "").strip().replace("\\", "/")
        if not raw:
            return Resolution(error="filename 为空")

        skill_dir = skill.directory.resolve()
        tried: list[str] = []

        # ① 绝对路径 + ② Skill 目录相对 + ③ 项目根相对：精确匹配
        for label, candidate in (
            ("绝对路径", Path(raw)),
            ("Skill 目录相对", skill_dir / raw),
            ("项目相对", self.project_root / raw),
        ):
            if label != "绝对路径" and Path(raw).is_absolute():
                continue
            if not candidate.exists():
                tried.append(label)
                continue
            resolved = candidate.resolve()
            if not _is_inside(resolved, skill_dir):
                return Resolution(
                    error=(
                        f"拒绝读取：{filename} 解析到 Skill 目录之外（{resolved}）。"
                        f"只能读取该 Skill 目录内的文件。"
                    )
                )
            if resolved.is_file():
                return Resolution(path=resolved)

        # ④ 只给文件名/片段：在 Skill 目录内递归搜索
        needle = Path(raw).name.lower()
        matches = [
            p
            for p in skill_dir.rglob("*")
            if p.is_file()
            and (p.name.lower() == needle or p.as_posix().lower().endswith(raw.lower()))
        ]
        matches = [m for m in matches if _is_inside(m.resolve(), skill_dir)]

        if len(matches) == 1:
            return Resolution(path=matches[0].resolve())
        if len(matches) > 1:
            return Resolution(
                candidates=sorted(m.relative_to(skill_dir).as_posix() for m in matches)
            )
        return Resolution(
            error=f"在 Skill「{skill.name}」目录内找不到 {filename}（已尝试：精确路径、递归搜索）"
        )

    # ---------------- 概览 ----------------
    def summary(self) -> str:
        head = f"技能目录：{self.root}（来源：{self.source}）"
        detail = f"已注册 {len(self.skills)} 个 Skill"
        if self.skipped:
            detail += "；跳过 " + "、".join(f"{n}（{r}）" for n, r in self.skipped)
        return f"{head}｜{detail}"


def _one_line(text: str) -> str:
    """把多行 description 压成单行，用于 Prompt 列表。"""
    return re.sub(r"\s+", " ", text).strip()


def _is_inside(path: Path, directory: Path) -> bool:
    """判断 path 是否在 directory 内（防 ../ 越界与符号链接逃逸）。"""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def load_registry(start: Path | None = None) -> SkillRegistry:
    """便捷入口：按当前工作目录发现并注册技能。"""
    return SkillRegistry.discover(start)
