# -*- coding: utf-8 -*-
"""演示辅助：把两条教学实践技能「备份 + 清空」，方便在老师面前现场用 createSkill 重建。

用法：
    python demo_skill_reset.py --status    # 查看当前状态
    python demo_skill_reset.py --backup    # 备份到 %TEMP%\\xagent_skill_backup 后删除
    python demo_skill_reset.py --restore   # 从备份还原

只处理 mini-encryption 与 officecli 两个目录，不影响其它技能。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skills import SkillRegistry  # noqa: E402

TARGETS = ("mini-encryption", "officecli")
BACKUP = Path(os.environ.get("TEMP", r"C:\Windows\Temp")) / "xagent_skill_backup"


def status(root: Path) -> None:
    print(f"技能目录：{root}")
    print(f"备份目录：{BACKUP}")
    reg = SkillRegistry.discover()
    print(f"已注册 {len(reg.skills)} 个技能：")
    for s in reg.skills.values():
        mark = "★" if s.slug in TARGETS else " "
        print(f"  {mark} {s.name:<22} {s.description[:44]}")
    print()
    for name in TARGETS:
        present = (root / name).is_dir()
        backed = (BACKUP / name).is_dir()
        print(f"  {name:<16} 技能目录：{'有' if present else '无'}"
              f"    备份：{'有' if backed else '无'}")


def backup(root: Path) -> int:
    BACKUP.mkdir(parents=True, exist_ok=True)
    removed = 0
    for name in TARGETS:
        src = root / name
        if not src.is_dir():
            print(f"  跳过 {name}（不存在）")
            continue
        dst = BACKUP / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        shutil.rmtree(src)
        print(f"  已备份并删除 {name} → {dst}")
        removed += 1
    print(f"\n完成：清空 {removed} 个技能，备份在 {BACKUP}")
    if removed:
        print("现在可以在 Agent 里现场演示：")
        print('  截图第 1 条：通过 createSkill 创建 miniEncryption 技能，'
              '用户说「加密保存」时把数字换成中文')
        print('  截图第 2 条：通过 createSkill 创建 OfficeCLI 技能（让 Agent 能调用 officecli-win-x64.exe）')
        print("演示结束后执行：python demo_skill_reset.py --restore")
    return 0


def restore(root: Path) -> int:
    if not BACKUP.is_dir():
        print(f"备份目录不存在：{BACKUP}")
        return 1
    restored = 0
    for name in TARGETS:
        src = BACKUP / name
        if not src.is_dir():
            print(f"  备份中没有 {name}，跳过")
            continue
        dst = root / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"  已还原 {name}")
        restored += 1
    print(f"\n完成：还原 {restored} 个技能")
    reg = SkillRegistry.discover()
    print("当前注册：", ", ".join(reg.names()))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="教学实践技能备份/清空/还原")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backup", action="store_true", help="备份后删除两个技能")
    group.add_argument("--restore", action="store_true", help="从备份还原")
    group.add_argument("--status", action="store_true", help="查看状态")
    args = parser.parse_args()

    root = SkillRegistry.discover().root
    if args.backup:
        return backup(root)
    if args.restore:
        return restore(root)
    status(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
