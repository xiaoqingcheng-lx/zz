# -*- coding: utf-8 -*-
"""结束 pethospital.exe，进程冻结后把 pet.db 同步到目标位置。

用法：
    python kill_pethospital.py <源 pet.db> <目标 pet.db>

例：
    python kill_pethospital.py .\\data\\pet.db D:\\backup\\pet.db
"""
import os
import shutil
import subprocess
import sys
import time


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


def main():
    if len(sys.argv) < 3:
        sys.exit("用法：python kill_pethospital.py <源 pet.db> <目标 pet.db>")
    src_db, dst_db = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])

    if not os.path.isfile(src_db):
        sys.exit("源文件不存在：%s" % src_db)

    pids = list_pids()
    print("找到进程 PID:", pids if pids else "无（未运行）")

    for pid in pids:
        k = subprocess.run(
            ["taskkill", "/PID", pid, "/F"],
            capture_output=True, text=True, encoding="gbk", errors="replace",
        )
        print("  结束 PID %s -> rc=%s %s" % (pid, k.returncode, (k.stdout or k.stderr).strip()))

    time.sleep(2)

    left = list_pids()
    print("剩余进程:", left if left else "已全部结束")
    if left:
        print("进程未彻底结束，中止同步")
        return 1

    # 进程停了，源数据库已冻结，同步最新版本
    os.makedirs(os.path.dirname(dst_db) or ".", exist_ok=True)
    shutil.copy2(src_db, dst_db)
    print("pet.db 已同步 ->", dst_db, os.path.getsize(dst_db), "字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
