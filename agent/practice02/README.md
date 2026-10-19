# practice02 · MCP 工具练习

一个最小的 MCP 服务，练习"给服务加工具"。目前 11 个工具，分两组：

**时间与日期**

| 工具 | 作用 | 实现方式 |
|---|---|---|
| `getDate` | 取当前电脑的日期和时间 | **调用本机 `date` 命令**，不写日期计算逻辑 |
| `isleapyear` | 判断输入年份是否闰年 | **纯 Python 代码计算**（公历规则） |

**本地文件操作**

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `get_cwd` | 取当前工作目录 | 无 |
| `list_files` | 列目录下的文件与子目录 | `path`、`recursive` |
| `get_file_type` | 判断文件类型（后缀 / MIME / 是否纯文本） | `path` |
| `read_file` | 读文本内容 | `path`、`max_bytes` |
| `create_file` | 在指定目录按文件名新建文件 | `directory`、`filename`、`content` |
| `update_file` | 改写或追加纯文本内容 | `path`、`content`、`mode` |
| `create_dir` | 新建目录（父级自动创建） | `directory` |
| `delete_dir` | 删除目录，可删非空 | `path`、`recursive` |
| `delete_file` | 删除文件 | `path` |

## 目录结构

```
practice02/
├── server.py              # 装配 MCPServer，注册全部工具
├── tools/
│   ├── __init__.py        # 工具登记处（新增工具改这里）
│   ├── get_date.py        # getDate
│   ├── is_leap_year.py    # isleapyear
│   └── file_ops.py        # 文件操作组（9 个工具）
├── requirements.txt
└── README.md
```

## 安装

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

（网络走代理时 pip 可能解析不到索引，加 `--proxy ""` 走直连。）

## 运行

```bat
.venv\Scripts\python.exe server.py
```

默认 **stdio** 传输，标准输入输出就是协议通道，所以直接双击运行会"没反应"，需要由 MCP 客户端拉起。

## 接入 MCP 客户端

把下面这段加进客户端的 MCP 配置（路径按自己机器改）：

```json
{
  "mcpServers": {
    "practice02": {
      "command": "D:\\大语言模型\\agent\\practice02\\.venv\\Scripts\\python.exe",
      "args": ["D:\\大语言模型\\agent\\practice02\\server.py"]
    }
  }
}
```

## 时间与日期两个工具的行为

### `getDate`（无参数）

按顺序找本机的 `date` 命令，返回一行文本：

```
2026-10-19 10:01:51 Monday +0800
```

查找顺序：

1. `PATH` 里的 `date`（Git Bash / MSYS2 / Linux / macOS 自带）；
2. Git for Windows 常见安装目录下的 `usr/bin/date.exe`；
3. 都没有时退回 `cmd /c date /t` + `cmd /c time /t`（Windows 内建命令）。

三种都是调用本地命令，代码里没有任何 `datetime.now()` 之类的自己算时间的逻辑。

### `isleapyear(year)`

`year` 取 1–9999 的整数，按公历规则计算：能被 4 整除；整百年必须还能被 400 整除。

| 年份 | 结果 |
|---|---|
| 2024 | 闰年（366 天，2 月 29 天） |
| 2023 | 平年（365 天） |
| 1900 | 平年（整百但不能被 400 整除） |
| 2000 | 闰年（整百且能被 400 整除） |

## 文件操作组的约束

这组工具直接动磁盘，所以做了几条限制：

| 场景 | 行为 |
|---|---|
| 读/写二进制文件（含 NUL 字节） | 拒绝，返回 `读取失败：…看起来是二进制文件` / `编辑失败：…只支持纯文本` |
| 往 `SystemRoot`、`Program Files`、`ProgramData` 下写或删 | 拒绝 |
| `create_file` 目标已存在 | 拒绝，提示改用 `update_file`，**绝不覆盖** |
| `filename` 带 `../` 或路径分隔符 | 拒绝（只接受单个文件名） |
| `delete_dir` 目标是磁盘根目录 | 拒绝 |
| `delete_dir` 目标是当前工作目录或其上级 | 拒绝 |
| `delete_dir` 非空且 `recursive=false` | 拒绝，提示改传 `true` |
| `delete_file` 传的是目录 | 拒绝，提示用 `delete_dir` |
| `read_file` 超过 `max_bytes` | 只返回开头并注明截断（默认上限 200 KB） |
| `list_files` 递归超过 2000 项 | 截断并提示 |
| 编码 | 读：UTF-8（含 BOM）→ GBK 依次尝试；写：固定 UTF-8 无 BOM |

⚠️ **删除不可恢复**：`delete_dir` / `delete_file` 直接走文件系统删除，**不进回收站**。
这是有意的设计（MCP 工具层没有回收站接口），调用前请确认路径。

`update_file` 的两种模式：

- `overwrite`（默认）：整体替换文件内容；
- `append`：追加到末尾，原文件末尾没有换行时自动补一个。

## 再加一个工具

1. 在 `tools/` 下新建 `<tool_name>.py`，写 `TOOL_NAME`、`TOOL_DESCRIPTION`、`register(server)`；
2. 在 `tools/__init__.py` 里 import 它的 `register`，并在 `register_tools()` 加一行调用；
3. 重启服务即可。
