# -*- coding: utf-8 -*-
"""模拟全新终端：PATH = 注册表 系统PATH + 用户PATH，验证 node/npm/git 能否被找到。"""
import os
import subprocess
import winreg

SYS_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"


def read(hive, sub, name):
    try:
        k = winreg.OpenKey(hive, sub)
        v, _ = winreg.QueryValueEx(k, name)
        return os.path.expandvars(v)
    except (FileNotFoundError, OSError):
        return ""


sys_path = read(winreg.HKEY_LOCAL_MACHINE, SYS_ENV, "Path")
user_path = read(winreg.HKEY_CURRENT_USER, "Environment", "Path")
print("系统 PATH 长度:", len(sys_path))
print("用户 PATH 长度:", len(user_path))
print("用户 PATH 末尾片段:", user_path[-80:] if user_path else "(空)")
print()

fresh = dict(os.environ)
fresh["PATH"] = sys_path + ";" + user_path

print("=== 全新终端环境下的验证 ===")
for cmd in ["where node", "node --version",
            "where npm", "npm --version",
            "where git", "git --version",
            "git config --global --list",
            "npm ping"]:
    r = subprocess.run(cmd, shell=True, env=fresh,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    print("-" * 46)
    print("$", cmd)
    print(out if out else "(无输出)")
