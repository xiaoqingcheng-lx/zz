---
name: officecli
description: 用本地 officecli-win-x64.exe 读取、创建、修改、校验 Word/Excel/PowerPoint 文档时使用，免安装 Office，优先于 python-docx/openpyxl
---
# OfficeCLI（officecli-win-x64.exe）

## 课程要求（原始说明）
1. 已下载 OfficeCLI 的 Windows 版本，在 Windows 终端可以直接用 `officecli-win-x64.exe` 启动，
   这个 exe 就在当前项目的文件夹内；
2. 使用参考：`OfficeCli操作说明.md`；
3. 目标是让 Agent 能够调用本地 `officecli-win-x64.exe`，读取、创建和修改 Word、Excel、PowerPoint 文档。

## 怎么调用
统一用 `officeCli` 工具，参数只有一个 `args` 数组（不含程序名）。
工具会自动找到 exe——包括它自更新后把自己搬进 `OfficeCli_#SULP#_*` 子目录的情况，
所以**不要在命令里拼 exe 路径**，也不要通过 RunCli 去猜路径。

需要查更细的参数说明时，用 `loadSkill(name='officecli', filename='OfficeCli操作说明.md')`
读取完整手册（25KB，含每个元素可用的属性与取值）；日常命令看下面这份速查即可。

## 三条硬规则
1. **先查帮助再动手**：不确定元素名、属性名、取值格式时，先 `["help","docx","paragraph"]` 查一眼。
   一次查帮助胜过三轮试错。
2. **分层处理**：L1 读取/结构 → L2 元素级修改 → L3 原始 XML，能用高层就别碰 XML。
3. **改完必须复核**：用 `view <文件> text` 或 `validate <文件>` 确认结果，再向用户汇报。

## 常用命令（args 数组写法）
```
["create", "<文件>"]                                  # 新建，类型由扩展名决定
["view", "<文件>", "outline|text|stats|issues|html"]   # 查看
["get", "<文件>", "<路径>", "--depth", "2"]            # 取节点
["query", "<文件>", "<选择器>"]                        # CSS 式查询
["validate", "<文件>"]                                 # 校验 OpenXML
["add", "<文件>", "/body", "--type", "paragraph", "--prop", "text=正文"]
["set", "<文件>", "/Sheet1/A1", "--prop", "value=姓名", "--prop", "bold=true"]
["remove", "<文件>", "<路径>"]
["close", "<文件>"]                                    # 关闭常驻进程持有的文件
["help", "docx", "paragraph"]                          # 查 schema
["--version"]
```

## 各格式要点
- **Word**：正文根节点是 `/body`；标题用 `--prop style=Heading1`；段落文本用 `--prop text=...`
- **Excel**：单元格路径 `/Sheet1/A1`；写入用 `--prop value=...`（不是 `text`）
- **PPT**：新建页用 `["add", 文件, "/", "--type", "slide"]`（父路径只能是 `/`，
  写 `/slide` 会报 Invalid parent）；之后页路径 `/slide[1]`；
  `shape[1]` 通常是标题占位符，正文从 `shape[2]` 开始；加文本框用
  `["add", 文件, "/slide[1]", "--type", "shape", "--prop", "text=..."]`

## 顺序很重要
- `add` 默认**追加到末尾**，必须按最终顺序逐条添加（先标题、再正文、最后落款）；
- 顺序错了用 `["move", 文件, "<被移动的路径>", "<目标位置>"]` 调整，或 `remove` 后按正确顺序重加；
- **核对顺序只能用 `view <文件> text`**：`view outline` 只输出标题层级、看不到正文，
  拿它「确认顺序」会得出错误结论；
- 汇报前必须看到 `view text` 的真实输出，不要把「应该是这样」当成结果讲给用户。

## 常见坑
| 错误做法 | 正确做法 |
|---|---|
| `--name "foo"` | 属性一律走 `--prop name="foo"` |
| 猜属性名 | 先 `help <格式> <元素>` 查 |
| 文本里直接写 `\n` | 写成 `\\n`，或改用 batch 批量操作 |
| 文件正被 PowerPoint/WPS 打开时修改 | 先关掉 Office 里的文件 |
| 想索引 `/shape[myname]` | 不支持，用数字下标或 `@name=`（仅 PPT） |
| `--type heading` 当标题 | 只支持 paragraph，标题要 `--prop style=Heading1` |

## 报错速查（照做即可，别重试同样的命令）
| 报错 | 处理 |
|---|---|
| `currently opened by a resident process` | 先 `["close", "<文件>"]`；只是加内容时不需要重新 create |
| `Unknown element type 'X'` | `--type` 只收 paragraph/run/table/row/cell/picture/chart；标题用 paragraph + style |
| `File already exists` | `create` 只能新建；改文件名，或直接对现有文件 `add`/`set` |
| `Unknown option --force` | `create` 没有 `--force`；要重建就先 `["close", 文件]`，删掉文件再 `create` |
| 属性名报错 | `["help", "<格式>", "<元素>"]` 查准确名称 |
| 同一命令连续失败两次 | 停下来查 help 或换方案，不要试第三次 |

## 交付前
- 给用户完整文件路径，并说明做了什么（几段文字、几个单元格、几页）；
- 用户原文件不宜覆盖时，另存为新文件名再改。
