# -*- coding: utf-8 -*-
"""逐项送入回收站并报告每项结果码，用于定位失败原因。"""
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

CODES = {
    0: "成功",
    2: "部分/全部文件无法处理",
    7: "路径无效或过长",
    0x7C: "路径过长(124)",
    0x78: "路径被占用(120)",
    0x20: "共享冲突(32)",
    5: "拒绝访问",
}


def recycle_one(path):
    from_str = path + "\0\0"
    buf = ctypes.create_unicode_buffer(from_str)
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_wchar_p)
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    return shell32.SHFileOperationW(ctypes.byref(op))


src = sys.argv[1]
for name in sorted(os.listdir(src)):
    full = os.path.join(src, name)
    code = recycle_one(full)
    still = os.path.exists(full)
    status = "OK" if not still else "FAIL"
    print(f"[{status}] {name:<40} code={code:<5} ({CODES.get(code, '未知')})")

print()
left = sorted(os.listdir(src))
print("剩余项:", left if left else "无，目录已清空")
