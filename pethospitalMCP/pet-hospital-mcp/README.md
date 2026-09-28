# 🐾 pet-hospital-mcp

把已有的 **Go 宠物医院 REST API** 适配成 **MCP 服务**，让 AI Agent 能通过标准 MCP 协议查询宠物档案。

```text
AI Agent / Agent 宿主
        │  MCP over Streamable HTTP（无状态，2026-07-28）
        ▼
pet-hospital-mcp  ← 本仓库（Python 3.11+，独立进程，6 个只读工具）
        │  HTTP（GET /api/v1/pets、/pets/{id}、/stats 等）
        ▼
Go 宠物医院服务（pethospital.exe，唯一后端，不修改）
```

---

## 1. 边界与约束

| 项 | 约定 |
| --- | --- |
| 🚧 后端唯一 | Go 服务是唯一数据源，**本仓库不修改 Go 代码**，也不直连 `data/pet.db` |
| 🔌 访问方式 | MCP 进程只通过 HTTP 调用 Go 服务，基地址由 `PET_HOSPITAL_BASE_URL` 指定 |
| 📖 只读 | 6 个工具全部是只读查询，不会写入/修改任何数据 |
| 🔒 默认仅本机 | MCP 默认监听 `127.0.0.1`；改 `MCP_HOST` 才对外，且仅适用于教学/内网 |
| 🔑 无鉴权 | 无鉴权、无 CORS、无 Origin 白名单校验（教学项目定位） |
| 🧩 工具数量 | **6 个，全部只读**：`list_pets`（阶段一）+ `get_pet` / `list_pet_records` / `list_pet_charges` / `get_pet_summary` / `get_stats`（阶段二）。**没有任何写操作工具**（详见第 14 节） |

---

## 2. 技术选型

| 项 | 取值 | 说明 |
| --- | --- | --- |
| MCP 协议版本 | `2026-07-28` | 无状态核心 |
| 官方 Python SDK | `mcp==2.0.0` | 使用 `mcp.server.MCPServer` |
| 传输 | Streamable HTTP，**无状态** | `stateless_http=True` + `json_response=True` |
| HTTP 客户端 | `httpx` | 只调上游 REST |
| 数据模型 | `pydantic` v2 | 严格入参校验 + 出参强类型 |
| ASGI | `uvicorn` | 承载 `MCPServer.streamable_http_app()` |

**明确没有使用的旧机制**（2026-07-28 已移除）：

- ❌ `mcp.server.fastmcp.FastMCP`（SDK 2.x 已改名 `MCPServer`，本项目不导入旧路径）
- ❌ `initialize` 握手 —— 由可选的 `server/discover` RPC 取代
- ❌ `Mcp-Session-Id` 请求/响应头
- ❌ 会话存储、会话过期、`max_sessions`
- ❌ 有状态 SSE 断线重连/事件恢复

每个请求自带 `_meta` 信封（协议版本 / 客户端信息 / 客户端能力），服务端不保存任何请求间状态。

---

## 3. 目录结构

```text
pet-hospital-mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py          # 对外公开名，__version__
│       ├── __main__.py          # 启动入口（python -m pet_hospital_mcp）
│       ├── config.py            # 环境变量 → Settings
│       ├── server.py            # 组装 MCPServer、注册工具、挂 /health
│       ├── rest_client.py       # 调用 Go REST API（超时 / 有限重试 / 错误映射）
│       ├── middleware.py        # 契约中间件：严格校验 + 统一错误 + 调用日志
│       ├── upstream.py          # Go 响应信封与出参模型（纯模型，无内部依赖）
│       ├── errors.py            # 错误码 + 统一错误信封
│       ├── logging_config.py    # JSON 日志 + 敏感字段递归脱敏
│       └── tools/
│           ├── __init__.py      # 自动发现并注册工具
│           ├── _shared.py       # 工具层共享入参（PetIdInput）
│           ├── list_pets.py     # 阶段一：列表查询
│           ├── get_pet.py       # 阶段二：按编号查单只
│           ├── list_pet_records.py    # 阶段二：历史病历
│           ├── list_pet_charges.py    # 阶段二：消费明细
│           ├── get_pet_summary.py     # 阶段二：费用与就诊汇总
│           └── get_stats.py     # 阶段二：全医院经营统计
└── tests/
    ├── conftest.py
    ├── helpers.py
    ├── test_config.py
    ├── test_rest_client.py
    ├── test_input_validation.py
    ├── test_tool_schema.py
    ├── test_server_http.py
    ├── test_stage2_tools.py
    └── test_logging_redaction.py
```

> `tools/` 是唯一需要扩展的地方：加工具 = 在 `tools/` 新增一个模块，实现 `register(server, client)` 与 `INPUT_MODEL` 即可，`tools/__init__.py` 会自动发现，无需改 REST 客户端、错误约定或日志。
>
> 依赖方向是**单向**的：`upstream.py` → `rest_client.py` → `tools/*` → `server.py`。上游出参模型之所以放在包根而不是 `tools/` 下，是因为 `rest_client` 要导入它们，而 `tools/__init__.py` 又要导入 `rest_client` —— 放一起会形成循环导入。

---

## 4. 安装

要求 **Python 3.11+**。

```bash
cd pet-hospital-mcp

# 推荐：虚拟环境
python -m venv .venv
.venv\Scripts\activate            # Windows（PowerShell/CMD）
# source .venv/bin/activate       # macOS / Linux

# 安装（含测试依赖）
pip install -e ".[dev]"

# 只装运行时
pip install -e .
```

安装后会得到命令 `pet-hospital-mcp`，等价于 `python -m pet_hospital_mcp`。

---

## 5. 配置（环境变量）

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | 上游 Go 宠物医院 REST API 基地址 |
| `MCP_HOST` | `127.0.0.1` | MCP 服务监听地址（默认仅本机） |
| `MCP_PORT` | `8000` | MCP 服务监听端口 |
| `MCP_PATH` | `/mcp` | MCP 端点路径 |
| `PET_HOSPITAL_TIMEOUT` | `10` | 单次上游请求超时（秒） |
| `PET_HOSPITAL_MAX_RETRIES` | `2` | 上游失败后的**额外**重试次数（有限重试） |
| `PET_HOSPITAL_TRUST_ENV` | `false` | 是否让 httpx 读取 `HTTP_PROXY`/`NO_PROXY`。默认关闭：上游是本机地址，跟随系统代理只会带来难查的失败 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

配置非法（例如 `PET_HOSPITAL_BASE_URL` 不是 `http://`/`https://` 开头）会在启动时直接报错并以退出码 `2` 结束，不会带病运行。

---

## 6. 启动

### 6.1 先启动 Go 服务（必须）

MCP 只是适配层，**Go 服务必须先跑起来**。

```bash
cd ..                              # 到放置 pethospital.exe 的目录
pethospital.exe                    # 默认 127.0.0.1:8080，数据文件 ./data/pet.db
```

确认可用：

```bash
curl http://127.0.0.1:8080/health
# {"code":200,"message":"ok","data":{"petCount":1008,"status":"healthy",...}}
```

### 6.2 再启动 MCP 服务

```bash
cd pet-hospital-mcp
python -m pet_hospital_mcp
```

启动后会打印横幅：

```text
  pet-hospital-mcp v0.1.0  (MCP 2026-07-28 · 官方 Python SDK 2.0.0)
    上游 Go REST API : http://127.0.0.1:8080
    MCP 端点         : http://127.0.0.1:8000/mcp
    健康检查         : http://127.0.0.1:8000/health
    工具             : list_pets
    传输             : Streamable HTTP，无状态（无会话、无 Mcp-Session-Id）
```

自定义端口示例：

```bash
MCP_PORT=9000 PET_HOSPITAL_BASE_URL=http://127.0.0.1:8080 python -m pet_hospital_mcp
```

> 注意：若系统设置了 `HTTP_PROXY` / `HTTPS_PROXY`，本地回环地址可能被代理劫持（表现为莫名其妙的 404）。本项目已默认 `PET_HOSPITAL_TRUST_ENV=false` 规避；用其他 HTTP 客户端手工验证时请自行设置 `NO_PROXY=127.0.0.1,localhost`。

---

## 7. 服务端点

| 端点 | 说明 |
| --- | --- |
| `POST /mcp` | MCP 端点（Streamable HTTP，无状态） |
| `GET /health` | 健康检查，始终 200（只报告本进程状态） |
| `GET /health?probe=upstream` | 额外探测上游 Go 服务；上游不可用时 `upstream.status = "down"`，但 HTTP 仍为 200 |

`/health` 返回示例：

```json
{
  "status": "ok",
  "service": "pet-hospital-mcp",
  "protocolVersion": "2026-07-28",
  "sdkVersion": "2.0.0",
  "mcpEndpoint": "/mcp",
  "upstreamBaseUrl": "http://127.0.0.1:8080",
  "tools": ["list_pets"],
  "upstream": {"status": "up"}
}
```

---

## 8. 工具清单

6 个工具，**全部只读**，参数与 Go 后端一一对应，不新增任何适配器私有业务参数。

| 工具 | 上游接口 | 一句话 |
| --- | --- | --- |
| `list_pets` | `GET /api/v1/pets` | 跨档案的列表查询：过滤 + 排序 + 分页 |
| `get_pet` | `GET /api/v1/pets/{id}` | 按编号取单只宠物的**完整档案** |
| `list_pet_records` | `GET /api/v1/pets/{id}/records` | 单只宠物的**历史病历** |
| `list_pet_charges` | `GET /api/v1/pets/{id}/charges` | 单只宠物的**消费明细**与分类小计 |
| `get_pet_summary` | `GET /api/v1/pets/{id}/summary` | 单只宠物的**费用与就诊汇总** |
| `get_stats` | `GET /api/v1/stats` | **全医院**经营统计（含消费排行） |

选择建议：先用 `list_pets` 找到目标档案的 `id`，再用按 id 的四个工具下钻；
只想要汇总数字时优先 `get_pet_summary`（比同时调 records + charges 省 token）；
要全量口径统计用 `get_stats`（它**不接受过滤条件**）。

### 8.1 `list_pets` —— 列表查询

把 Go 的 `GET /api/v1/pets` 适配成 MCP 工具，参数与后端**一一对应**，不新增任何适配器私有参数。

#### 参数（全部可选）

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `q` | string | 跨字段全文关键词（宠物名/主人/电话/疾病/医生/病历全文；空格分词为 AND） |
| `name` | string | 宠物姓名模糊匹配 |
| `ownerName` | string | 主人姓名模糊匹配 |
| `ownerPhone` | string | 主人电话模糊匹配 |
| `species` | enum | 精确匹配：`犬` `猫` `兔` `鸟` `仓鼠` `爬宠` `其他` |
| `doctor` | string | 主治医生模糊匹配 |
| `disease` | string | 疾病/诊断模糊匹配 |
| `status` | enum | 精确匹配：`待就诊` `就诊中` `住院中` `已康复` `慢性病随访` |
| `min` | number ≥ 0 | 总花费下限（元，含边界） |
| `max` | number ≥ 0 | 总花费上限（元，含边界）；与 `min` 同时给出时必须 `min <= max` |
| `sortBy` | enum | `id` `name` `ownerName` `species` `doctor` `disease` `status` `totalCost` `visitCount` `createdAt` `updatedAt` |
| `order` | enum | `asc` / `desc` |
| `page` | int ≥ 1 | 页码，默认 `1` |
| `pageSize` | int 1–500 | 每页条数，默认 `20` |

严格校验规则：**拒绝未知字段**、**拒绝类型强转**（`"2"` / `1.5` / `true` 均不合法）、**拒绝 `NaN` / `Infinity`**、拒绝枚举越界、拒绝区间越界。

#### 返回值

成功时返回结构化结果，字段与 Go 成功响应里的 `data` 完全一致：

| 字段 | 说明 |
| --- | --- |
| `items` | 当前页档案数组。每项含 `id/name/species/breed/gender/ageMonths/color/chipNo/ownerName/ownerPhone/ownerAddr/doctor/disease/status/allergy/note/records/charges/totalCost/visitCount/createdAt/updatedAt` |
| `total` | 过滤后的档案总数 |
| `page` / `pageSize` / `totalPages` | 分页信息 |
| `totalCost` | 当前过滤结果集的总花费合计（元） |

`records` 与 `charges` 在 Go 侧可能序列化为 `null` 也可能是数组，两者都被接受。

#### 调用示例

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_pets",
    "arguments": {
      "species": "犬",
      "min": 1000,
      "sortBy": "totalCost",
      "order": "desc",
      "page": 1,
      "pageSize": 3
    },
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientInfo": {"name": "curl", "version": "1.0"},
      "io.modelcontextprotocol/clientCapabilities": {}
    }
  }
}
```

### 8.2 `get_pet` —— 按编号取单只

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string（必填） | 档案编号，形如 `PET-000001` |

`id` 由系统生成、客户端不能自定义，因此适配器会校验形状（`^PET-[0-9]{1,12}$`，允许首尾空白并自动去除）。
形状不合法 → `VALIDATION_ERROR`；形状合法但档案不存在 → `BACKEND_API_ERROR`（`details.status = 404`，`message` 为上游的中文说明）。

返回单只宠物的完整档案对象，字段与 `list_pets` 的 `items[]` 元素一致（含 `records` / `charges`）。

### 8.3 `list_pet_records` —— 历史病历

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string（必填） | 档案编号 |

返回 `petId` / `petName` / `ownerName` / `count` / `records[]` / `historyText`。
每条病历含 `visitDate` / `doctor` / `diagnosis` / `symptoms` / `treatment` / `prescription[]` /
`weightKg` / `temperature` / `followUp` / `charge` / `createdAt`。
`records` 在 Go 侧空时是 `[]`（不是 `null`）。`historyText` 是上游生成的一行式病程摘录，可直接喂给模型。

### 8.4 `list_pet_charges` —— 消费明细

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string（必填） | 档案编号 |

返回 `petId` / `petName` / `count` / `charges[]` / `totalCost` / `costByCategory`。
每笔收费含 `item` / `category` / `amount` / `doctor` / `date` / `note`。
`costByCategory` 是按收费分类聚合的金额，例如 `{"检查": 880.34, "药品": 159.05}`。

### 8.5 `get_pet_summary` —— 费用与就诊汇总

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string（必填） | 档案编号 |

返回档案基本信息 + `totalCost` / `visitCount` / `chargeCount` /
`costByCategory` / `costByDoctor` / `maxSingleCharge` / `avgCostPerVisit` /
`firstVisit` / `lastVisit` / `historyText`。
`avgCostPerVisit` = `totalCost / visitCount`，无病历时为 `0`。

### 8.6 `get_stats` —— 全医院经营统计

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `top` | int 1–100 | 消费排行返回的档案条数，默认 `5` |

返回 `totalPets` / `totalRecords` / `totalCharges` / `totalRevenue` / `averageCost` / `maxCost` /
`bySpecies` / `byStatus` / `byDoctor` / `revenueByDoctor` / `topSpenders[]` / `logGarbagePct`。

两个要点：

- 这是**全量口径**，不接受任何过滤条件。要按条件统计请用 `list_pets` 的 `total` / `totalCost`。
- `logGarbagePct` 是底层单文件数据库的日志垃圾占比，运维参考，不是业务数据。

> 上游 `/api/v1/pets/top-spenders` 与 `/api/v1/pets/search` 这两个接口**没有**单独做成工具：
> 前者完全等价于 `list_pets(sortBy="totalCost", order="desc", pageSize=N)`，
> 后者的 Go 实现（`highlightAll`）是空操作、行为与 `list_pets?q=` 完全相同
> （且 `q` 还多了一层「跨字段 + 分词 AND」的说明）。
> 做两个同构工具只会让模型在选工具时犹豫，因此由 `list_pets` 覆盖。

---

## 9. 错误约定

工具失败时**不抛协议错误**，而是返回 `isError: true` 的工具结果，内容为统一错误信封：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "输入参数校验失败。",
    "details": {"fields": [{"field": "species", "reason": "Input should be '犬', '猫', ..."}]}
  }
}
```

| code | 含义 | 调用方建议 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 入参不合法（未知道字段/类型错误/枚举越界/区间越界/`min > max`） | 按 `details.fields` 改写参数后重试 |
| `BACKEND_TIMEOUT` | 调用上游超时 | 稍后重试 |
| `BACKEND_UNAVAILABLE` | 上游不可达 / 连接被拒绝 | 检查 Go 服务是否已启动 |
| `BACKEND_API_ERROR` | 上游应答了但业务失败（HTTP 4xx/5xx，或信封 `code != 200`） | 检查参数或上游状态 |
| `BACKEND_INVALID_RESPONSE` | 上游响应不是合法 JSON，或不符合约定模型 | 检查上游版本是否变更 |
| `INTERNAL_ERROR` | 适配器自身未预期错误（兜底） | 查服务端日志 |

**绝不泄漏** httpx / Pydantic / SDK / Python 堆栈原文。上游 5xx 与传输类错误会做有限重试（默认额外 2 次），4xx 不重试。

---

## 10. 日志

默认输出到 **stderr**，单行 JSON（下面是真实运行时的输出）：

```json
{"timestamp": "2026-09-17T02:52:17.484232+00:00", "level": "INFO", "logger": "pet_hospital_mcp.tool", "message": "tool_call", "tool_name": "list_pets", "params": {"species": "犬", "min": 1000, "sortBy": "totalCost", "order": "desc", "page": 1, "pageSize": 3}, "status": "ok", "duration_ms": 15.365}
{"timestamp": "2026-09-17T02:52:17.487815+00:00", "level": "INFO", "logger": "pet_hospital_mcp.tool", "message": "tool_call", "tool_name": "list_pets", "params": {"species": "恐龙"}, "status": "VALIDATION_ERROR", "duration_ms": 0.0}
{"timestamp": "2026-09-17T02:52:17.494026+00:00", "level": "INFO", "logger": "pet_hospital_mcp.tool", "message": "tool_call", "tool_name": "list_pets", "params": {"ownerPhone": "***"}, "status": "ok", "duration_ms": 1.855}
```

| 字段 | 说明 |
| --- | --- |
| `timestamp` | ISO 8601（UTC） |
| `tool_name` | 工具名 |
| `params` | 调用参数（**已脱敏**） |
| `status` | `ok`，或错误码（如 `VALIDATION_ERROR`、`BACKEND_TIMEOUT`、`INTERNAL_ERROR`） |
| `duration_ms` | 耗时（毫秒） |

**两层脱敏**：

1. **结构化脱敏** —— 对 `ownerPhone` / `ownerAddr` / `chipNo` 及其 snake_case / kebab-case / 大小写变体做**递归**替换为 `***`（字典、嵌套字典、数组都覆盖）；`JsonFormatter` 还会再兜一层，即使调用方忘了也不会漏。
2. **第三方库日志降噪** —— `httpx` / `httpcore` 会在 INFO 级别原样打印**完整请求 URL**，而查询串里可能带 `ownerPhone=138…`。脱敏无法改写第三方库已拼好的成品字符串，因此这两个 logger 被抬到 `WARNING`：既不泄漏敏感数据，又保留真正需要关注的告警。

> 验证：调用 `list_pets` 并传 `ownerPhone` 后，服务日志中只出现 `"ownerPhone": "***"`，原始号码不出现在任何一行。

---

## 11. 如何验证无状态连接与调用工具

### 11.1 最省事：官方 SDK 2.x 客户端

SDK 2.x 客户端直接用 URL 构造，**没有 `initialize` 握手**：

```python
import asyncio
from mcp import Client

async def main():
    async with Client("http://127.0.0.1:8000/mcp") as c:
        tools = await c.list_tools()
        print([t.name for t in tools.tools])          # 6 个工具

        r = await c.call_tool("list_pets", {
            "species": "猫", "pageSize": 2,
            "sortBy": "totalCost", "order": "desc",
        })
        print(r.is_error)                              # False
        print(r.structured_content["total"])

        # 阶段二：按编号下钻
        pet = await c.call_tool("get_pet_summary", {"id": "PET-000207"})
        print(pet.structured_content["totalCost"], pet.structured_content["maxSingleCharge"])

asyncio.run(main())
```

> 若本机设有系统代理，请先 `set NO_PROXY=127.0.0.1,localhost`。

### 11.2 纯 curl：验证「无状态」到底无状态在哪

下面的请求**没有**任何前置握手，也**不带** `Mcp-Session-Id`，服务端照样应答 —— 这就是无状态：

```bash
# ① 发现（替代 initialize）：直接把协议版本与客户端信息塞进 params._meta
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1.0"},"io.modelcontextprotocol/clientCapabilities":{}}}}' \
  -D - -o /dev/null | grep -i 'mcp-session-id\|HTTP/'
# 响应头里没有 Mcp-Session-Id → 无会话

# ② 调用工具（换成任意工具名与参数即可）
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' \
  -H 'Mcp-Name: get_pet_summary' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_pet_summary","arguments":{"id":"PET-000207"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1.0"},"io.modelcontextprotocol/clientCapabilities":{}}}}'
```

要点：

1. `_meta` 放在 **`params` 里**，不是 JSON-RPC 顶层；
2. 键名带命名空间前缀 `io.modelcontextprotocol/`，缺了会返回 `-32602` 参数错误；
3. `Mcp-Method` / `Mcp-Name` 是 HTTP 头，便于网关按工具路由；
4. 连续两次调用之间**没有任何服务端状态**，可以并发/乱序发、可以用不同客户端交替发。

### 11.3 MCP Inspector（图形界面）

```bash
npx @modelcontextprotocol/inspector
```

在界面中选 **Transport = Streamable HTTP**，URL 填 `http://127.0.0.1:8000/mcp`，连接后即可看到全部 6 个工具并直接调用。

### 11.4 本仓库附带的验收脚本（可选）

两个独立的开发期脚本，`pytest` 不收集它们，可直接运行做手工验收；确认无误后可删除：

```bash
# 走原始 HTTP + 真实 Go 服务：6 个工具 + 空结果集边界 + 5 类错误路径
python _e2e_check.py

# 走官方 SDK 2.x 客户端：逐个工具调用 + 404 路径
python _sdk_check.py
```

---

## 12. 测试

```bash
cd pet-hospital-mcp
pytest -q
```

预期结果（本机实测）：

```text
282 passed in 11.45s
```

测试**完全不依赖真实 Go 服务**：上游用 `httpx.MockTransport` 全量打桩，HTTP 契约测试会真实起一个 `uvicorn` 实例（随机空闲端口）后请求它。

| 测试文件 | 覆盖内容 |
| --- | --- |
| `test_config.py` | 环境变量解析、默认值、非法配置拒绝、URL/路径归一化 |
| `test_rest_client.py` | 14 个查询参数逐一转发、5xx 重试 / 4xx 不重试、超时/连接错误映射、坏 JSON / 坏模型 |
| `test_input_validation.py` | 严格校验（未知字段、类型、NaN/Inf、枚举、区间、`min > max`）、统一错误信封、不泄漏 Pydantic 原文 |
| `test_tool_schema.py` | 工具集完整性、命名、JSON Schema（枚举/边界/`additionalProperties: false`）、6 个工具描述体例 |
| `test_stage2_tools.py` | 5 个新工具：上游路径与参数转发、`null`/空数组兼容、404 与超时/坏模型映射、id 形状校验、**校验按工具名路由**、日志字段 |
| `test_server_http.py` | 无状态流程：无 `initialize`、无 `Mcp-Session-Id`、2026-07-28 发现与调用、`/health`、工具可发现性 |
| `test_logging_redaction.py` | 递归脱敏（大小写 / snake_case / kebab-case 变体）、第三方库日志降噪，日志不含原始敏感数据 |

---

## 13. 已知限制

- **只读适配 6 个接口**：Go 服务共有 29 个接口，本仓库只覆盖列表查询 + 5 个按 id 的只读查询；所有写操作与批量/导出/管理类接口都未适配。
- **无鉴权/无 CORS/无 Origin 校验**：仅适用于本地教学与内网演示，**请勿直接暴露到公网**。
- **返回值含个人信息**：档案与 `get_stats` 的 `topSpenders` 里含主人电话、住址、芯片号。日志侧已做递归脱敏，但这些字段确实会返回给模型，调用方需自行注意使用场合。
- **`totalCost` 末位小数可能抖动**：该值由 Go 侧对浮点数求和得到，同一查询多次调用末位可能有差异（实测同一参数连续三次得到 `…9983` / `…0006` / `…9994`），属上游行为，适配器原样透传、不做四舍五入。
- **`sortBy` 单独给出、不配 `order` 时**，排序方向由上游默认值决定。
- **上游 `top-spenders` 的 `total` 字段是全库档案数**（不是 `limit` 或排名数），语义容易误导，因此没有把它单独做成工具。

---

## 14. 明确声明：写操作类工具未实现

**本仓库的 6 个工具全部是只读查询，没有任何写操作工具。**

已实现（只读）：

`list_pets` · `get_pet` · `list_pet_records` · `list_pet_charges` · `get_pet_summary` · `get_stats`

未实现的接口（非完整清单）：

| 类别 | 未适配的接口 |
| --- | --- |
| 写操作 | `POST /api/v1/pets`、`PUT/PATCH/DELETE /api/v1/pets/{id}`、`POST .../records`、`POST .../charges` |
| 批量 / 导出 / 管理 | `POST /api/v1/pets/batch`、`batch-delete`、`GET /api/v1/export`、`POST /api/v1/admin/compact`、`admin/seed` |
| 高级查询（由 `list_pets` 覆盖，未单独建工具） | `by-owner`、`by-doctor`、`by-species`、`by-disease`、`by-status`、`cost-range`、`search`、`top-spenders` |
| 元数据 | `GET /api/v1/meta`、`GET /api/v1/endpoints`、`GET /`（网页界面）、`/health` |

`tools/` 目录已按「加工具零改造成本」设计，详见 `UPGRADE_PROMPT.md`。
