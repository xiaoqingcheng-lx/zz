# -*- coding: utf-8 -*-
"""结束 pethospital.exe，然后把最新的 pet.db 同步到 D:\\LLM。"""
import shutil
import subprocess
import sys
import time

SRC_DB = r"C:\Users\lx\OneDrive\Desktop\windows\data\pet.db"
DST_DB = r"D:\LLM\data\pet.db"


def list_pids():
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq pethospital.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, encoding="gbk", errors="replace",
    )
    pids = []
    for line in r.stdout.strip().splitlines():
        parts = line.split('","')
        if len(parts) > 1 and "pethospital" in parts[0].lower():
            pids.append(parts[1].strip('"'))
    return pids


pids = list_pids()
print("找到进程 PID:", pids if pids else "无（未运行）")

for pid in pids:
    k = subprocess.run(
        ["taskkill", "/PID", pid, "/F"],
        capture_output=True, text=True, encoding="gbk", errors="replace",
    )
    print(f"  结束 PID {pid} -> rc={k.returncode} {(k.stdout or k.stderr).strip()}")

time.sleep(2)

left = list_pids()
print("剩余进程:", left if left else "已全部结束")

if left:
    print("进程未彻底结束，中止同步")
    sys.exit(1)

# 进程停了，源 pet.db 已冻结，同步最新版本到 D 盘
shutil.copy2(SRC_DB, DST_DB)
import os
print("pet.db 已同步 ->", DST_DB, os.path.getsize(DST_DB), "字节")
