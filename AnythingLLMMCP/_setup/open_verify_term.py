"""打开一个新的 CMD 窗口，在里面验证 node / npm / git。

关键点：新窗口必须继承**从注册表读出的最新 PATH**，
而不是当前进程沿用的旧 PATH —— 否则演示的就不是"全新终端的真实情况"。
"""
import os
import subprocess
import sys
import winreg

CREATE_NEW_CONSOLE = 0x00000010


def read_reg_path(root, subkey):
    """从注册表读 Path 值（REG_EXPAND_SZ 需要展开环境变量）。"""
    try:
        key = winreg.OpenKey(root, subkey, 0, winreg.KEY_READ)
    except OSError:
        return ""
    try:
        value, _ = winreg.QueryValueEx(key, "Path")
        return os.path.expandvars(value)
    except FileNotFoundError:
        return ""
    finally:
        key.Close()


machine = read_reg_path(
    winreg.HKEY_LOCAL_MACHINE,
    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
)
user = read_reg_path(winreg.HKEY_CURRENT_USER, "Environment")

env = os.environ.copy()
env["PATH"] = machine + ";" + user

commands = " & ".join([
    "echo ===== Node / npm / Git 验证 =====",
    "node -v",
    "npm -v",
    "git --version",
    "echo.",
    "echo == 实际路径 ==",
    "where node",
    "where npm",
    "where git",
    "echo.",
    "echo == 按任意键关闭本窗口 ==",
    "pause",
])

proc = subprocess.Popen(
    ["cmd.exe", "/k", commands],
    creationflags=CREATE_NEW_CONSOLE,
    env=env,
)

print("已启动新 CMD 窗口，PID =", proc.pid)
print("用户 PATH 含 AnythingLLMMCP\\node    :", "AnythingLLMMCP\\node" in user)
print("用户 PATH 含 AnythingLLMMCP\\git\\cmd :", "AnythingLLMMCP\\git\\cmd" in user)
