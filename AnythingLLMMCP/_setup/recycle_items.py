# -*- coding: utf-8 -*-
"""把给定的任意个路径（文件或文件夹）送入 Windows 回收站。
用法: python recycle_items.py "C:\\path1" "C:\\path2" ...
"""
import ctypes
import os
import sys
from ctypes import wintypes


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


shell32 = ctypes.windll.shell32
shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
shell32.SHFileOperationW.restype = ctypes.c_int

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400
FOF_SILENT = 0x0004

CODES = {0: "成功", 2: "部分/全部无法处理(通常是被占用)", 0x7C: "文件无效或被占用",
         0x78: "源拒绝访问", 0x79: "路径太深", 0x81: "文件名过长"}


def recycle_one(path):
    buf = ctypes.create_unicode_buffer(path + "\0\0")
    op = SHFILEOPSTRUCTW(
        None, FO_DELETE, ctypes.cast(buf, ctypes.c_wchar_p), None,
        FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT,
        False, None, None,
    )
    return shell32.SHFileOperationW(ctypes.byref(op))


targets = sys.argv[1:]
if not targets:
    print("用法: python recycle_items.py <path1> [path2] ...")
    sys.exit(2)

for p in targets:
    if not os.path.exists(p):
        print(f"[SKIP] 不存在: {p}")
        continue
    kind = "目录" if os.path.isdir(p) else "文件"
    code = recycle_one(p)
    gone = not os.path.exists(p)
    print(f"[{'OK' if gone else 'FAIL'}] ({kind}) {p}  code={code} ({CODES.get(code, '未知')})")
