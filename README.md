# 大语言模型练习仓库

课程练习与实训过程中的代码，按目录分开存放。

## 目录结构

| 目录 | 内容 |
|---|---|
| `agent/` | 调用 DashScope 的对话大模型：终端版 `llm_cli.py`、弹窗版 `llm_gui.py`、一次性版 `llm.py` |
| `agent/practice01/` | 会话记录归档（jsonl 原始件 + 可读 md，密钥已脱敏） |
| `agent/practice02/` | MCP 工具服务：11 个工具 + 流式对话启动文件 + Mermaid 架构图 |
| `AnythingLLMMCP/_setup/` | AnythingLLM 的 MCP 环境配置脚本（PATH、快捷菜单等） |
| `pethospitalMCP/` | 宠物医院 MCP 教学项目（Go 服务 + Python 客户端） |

## 运行前准备

**API Key 不在仓库里。** 需要自己准备同目录的 `config.ini`：

```ini
[llm]
base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
api_key  = sk-你的key
model    = qwen-plus
```

`config.ini` 与 `_secret.py` 已被 `.gitignore` 排除。

## agent：对话大模型

需要 Python 3.10+。

```bat
cd agent

python llm_cli.py "你好"          :: 终端版，带上下文循环
python llm.py "你好"              :: 一次性问答，单文件
python llm_gui.py                 :: 弹窗版，带"记忆上文"开关
```

Windows 上也可以直接双击 `run_cli.bat` / `run_gui.bat`（会自动找带 tkinter 的 Python）。

## agent/practice02：MCP 工具服务

```bat
cd agent\practice02
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt

.venv\Scripts\python.exe server.py                    :: 只起服务（stdio）
.venv\Scripts\python.exe demo.py                      :: 11 个工具逐个演示
.venv\Scripts\python.exe chat-stream-tool-fileops.py  :: 流式对话 + 模型自主调工具
```

11 个工具：`getDate`、`isleapyear`、`get_cwd`、`list_files`、`get_file_type`、
`read_file`、`create_file`、`update_file`、`create_dir`、`delete_dir`、`delete_file`。

写/删操作有安全闸：拒绝系统目录（Windows / Program Files / ProgramData）、
拒绝磁盘根与当前工作目录、拒绝把二进制文件当文本处理。
注意删除不经回收站。

架构图见 `agent/practice02/chat-stream-tool-fileops-architecture.mmd`，
可粘贴到 [mermaid.live](https://mermaid.live) 查看，同目录也附了渲染好的 PNG。

## 说明

- `pethospitalMCP/pet-hospital-mcp-teaching-main/` 是教学用上游项目副本，非本人编写
- `agent/practice01/` 里的会话记录已做密钥脱敏，可直接公开阅读
