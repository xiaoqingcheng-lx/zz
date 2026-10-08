# -*- coding: utf-8 -*-
"""把 tools\node 和 tools\git\cmd 追加到当前用户 PATH（去重、保持 REG_EXPAND_SZ），并广播环境变更。"""
import ctypes
import winreg

ADD = [
    r"D:\LLM\AnythingLLMMCP\node",
    r"D:\LLM\AnythingLLMMCP\git\cmd",
]

key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                     winreg.KEY_READ | winreg.KEY_WRITE)
try:
    cur, typ = winreg.QueryValueEx(key, "Path")
except FileNotFoundError:
    cur, typ = "", winreg.REG_EXPAND_SZ

items = [p for p in cur.split(";") if p.strip()]
low = {p.rstrip("\\").lower() for p in items}

added = []
for p in ADD:
    if p.rstrip("\\").lower() not in low:
        items.append(p)
        added.append(p)

new = ";".join(items)
winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new)
winreg.CloseKey(key)

print("新增条目:", added if added else "无（已存在）")
print("--- 写入后的用户 PATH ---")
for p in items:
    print("  ", p)

# 广播 WM_SETTINGCHANGE，让新开的资源管理器/终端感知（不影响已开着的进程）
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002
res = ctypes.c_ulong()
ok = ctypes.windll.user32.SendMessageTimeoutW(
    HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
    SMTO_ABORTIFHUNG, 5000, ctypes.byref(res))
print("环境变更广播:", "OK" if ok else "失败(不影响写入)")
