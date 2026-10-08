# -*- coding: utf-8 -*-
"""为解压版 Git 补上资源管理器右键菜单：Git Bash Here / Git GUI Here（仅写 HKCU，无需管理员）。"""
import winreg

GIT = r"D:\LLM\AnythingLLMMCP\git"

ENTRIES = [
    # (父键, 项名, 显示名, 图标, 命令)
    (r"Software\Classes\Directory\shell", "git_shell", "Git Bash Here",
     GIT + r"\git-bash.exe", f'"{GIT}\\git-bash.exe" "--cd=%v."'),
    (r"Software\Classes\Directory\Background\shell", "git_shell", "Git Bash Here",
     GIT + r"\git-bash.exe", f'"{GIT}\\git-bash.exe" "--cd=%v."'),
    (r"Software\Classes\Directory\shell", "git_gui", "Git GUI Here",
     GIT + r"\cmd\git-gui.exe", f'"{GIT}\\cmd\\git-gui.exe" "--working-dir=%v."'),
    (r"Software\Classes\Directory\Background\shell", "git_gui", "Git GUI Here",
     GIT + r"\cmd\git-gui.exe", f'"{GIT}\\cmd\\git-gui.exe" "--working-dir=%v."'),
]

for parent, name, label, icon, cmd in ENTRIES:
    base = f"{parent}\\{name}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, label)
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base + r"\command", 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)

print("已注册右键菜单：")
for parent, name, label, *_ in ENTRIES:
    print(f"  HKCU\\{parent}\\{name}  ->  {label}")
