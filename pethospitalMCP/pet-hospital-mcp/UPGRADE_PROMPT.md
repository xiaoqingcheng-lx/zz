# UPGRADE_PROMPT.md

把这个文件整段复制给 AI（或作为下一阶段任务的提示词），即可在**不破坏现有约定**的前提下继续扩展本 MCP 服务。

---

## 一、给你的上下文

你正在维护 `pet-hospital-mcp`：一个把 **已有的 Go 宠物医院 REST API** 适配成 **MCP 服务**的独立 Python 服务。

- 技术栈：Python 3.11+、官方 Python SDK `mcp==2.0.0`、协议版本 `2026-07-28`、`mcp.server.MCPServer`、**无状态 Streamable HTTP**。
- Go 服务是**唯一后端**，**不允许修改 Go 代码**，也不允许直连 `data/pet.db`；只能通过 HTTP 调 `PET_HOSPITAL_BASE_URL`（默认 `http://127.0.0.1:8080`）。
- 当前**已有 6 个只读工具**（阶段一 1 个 + 阶段二 5 个）：

  | 工具 | 上游接口 |
  | --- | --- |
  | `list_pets` | `GET /api/v1/pets` |
  | `get_pet` | `GET /api/v1/pets/{id}` |
  | `list_pet_records` | `GET /api/v1/pets/{id}/records` |
  | `list_pet_charges` | `GET /api/v1/pets/{id}/charges` |
  | `get_pet_summary` | `GET /api/v1/pets/{id}/summary` |
  | `get_stats` | `GET /api/v1/stats` |

- 目录结构、端点、配置项、错误码、日志字段、工具集取舍理由见 `README.md`，**动手前先读它**。
- 当前测试基线：`cd pet-hospital-mcp && pytest -q` → `282 passed`。

**绝对不要做的事**（协议层面已废弃，违反即视为改造失败）：

1. 不要导入 `mcp.server.fastmcp.FastMCP`，不要用 1.x 的 API 习惯猜 2.x。
2. 不要实现 `initialize` 握手，不要读写 `Mcp-Session-Id`，不要做会话存储/过期/`max_sessions`。
3. 不要做有状态 SSE 断线重连或事件恢复；保持 `stateless_http=True`。
4. 不要把 `host` / `port` / `stateless_http` 传给 `MCPServer(...)` 构造器 —— 它们属于 `run()` / `streamable_http_app()`。
5. 不要用 `MCPError` 表示工具业务失败（它会被当成 JSON-RPC 协议错误，模型看不到）；业务失败必须抛 `ToolError`。
6. 不要让 httpx / Pydantic / SDK / Python 的原始报错文本或堆栈到达客户端。
7. 不要绕过 `ContractMiddleware` 的严格校验，也不要给工具增加后端没有的「适配器私有业务参数」。
8. 不要修改 Go 服务代码。
9. 不要把上游出参模型放回 `tools/` 目录下 —— 那会让 `rest_client` ↔ `tools/__init__` 循环导入。出参模型归 `src/pet_hospital_mcp/upstream.py`。

**不确定的 SDK 行为，先读已安装的 SDK 源码或写最小原型脚本实测，不要凭 FastMCP 1.x 的经验推断。**

---

## 二、剩余可做的工作

### 2.1 不要再加这些只读工具（已被覆盖）

以下接口看起来可以各做一个工具，但**实际上与现有工具同构或完全冗余**，加了只会让模型选工具时犹豫：

| 接口 | 为什么不做 |
| --- | --- |
| `GET /api/v1/pets/search?q=` | Go 侧 `highlightAll()` 是空实现，行为与 `list_pets` 的 `q` 参数**完全相同**（唯一差别是缺 `q` 时报 400）。 |
| `GET /api/v1/pets/top-spenders?limit=` | 等价于 `list_pets(sortBy="totalCost", order="desc", pageSize=limit)`。且它的 `total` 字段是全库档案数，语义容易误导。 |
| `by-owner` / `by-doctor` / `by-species` / `by-disease` / `by-status` / `cost-range` | 全部是 `list_pets` 已有过滤参数的子集。 |
| `GET /api/v1/meta` | 枚举字典，属于适配器**开发期**该读的资料（本项目已把真实允许值固化进 `Literal`），不是运行时给模型用的工具。 |
| `GET /api/v1/endpoints`、`GET /`、`/health` | 运维/网页用途，不是 Agent 任务。 |

如果确实要加 `by-*` 类工具，请先说服自己：模型用 `list_pets` 的对应参数做不到什么？做不到才加。

### 2.2 可以做的：写操作工具（**默认不做，需用户显式确认**）

未适配的写操作接口：

| 接口 | 风险 |
| --- | --- |
| `POST /api/v1/pets` | 新增档案 |
| `PUT /api/v1/pets/{id}` | **全量替换**，未传字段会被清空（含 `records` / `charges`），极易造成数据丢失 |
| `PATCH /api/v1/pets/{id}` | 局部更新，相对安全 |
| `DELETE /api/v1/pets/{id}` | 删除，**不可逆** |
| `POST /api/v1/pets/{id}/records` | 追加病历 |
| `POST /api/v1/pets/{id}/charges` | 追加收费，会改变 `totalCost` |
| `POST /api/v1/pets/batch` | 批量新增 |
| `POST /api/v1/pets/batch-delete` | 批量删除，**不可逆** |
| `GET /api/v1/export` | 导出全量数据（只读，但会返回全部档案，响应极大） |
| `POST /api/v1/admin/compact`、`admin/seed` | 管理操作，`seed` 会往库里灌数据 |

**开始之前必须先和用户确认**：哪些写操作要开放、是否需要二次确认机制、是否只开放 `PATCH` 这类低风险操作。
在没有明确授权时，**只做只读工具**。

若获授权，除了第 2.3 节的通用要求，写操作工具还要额外满足：

1. **工具描述里显式写出副作用**（会改什么字段、`PUT` 会清空未传字段、删除不可逆）。
2. **入参必须是该接口真正需要的最小集合**，不给「传什么就写什么」的通用口子。
3. **乐观并发提示**：Go 侧没有版本号，至少要在描述里提示模型「先 `get_pet` 拿当前值再改」。
4. **测试里必须有一条「写操作确实没有在只读路径上被调用」的守卫**。

### 2.3 加任何工具时必须同时满足

1. **零改造成本**：只在 `src/pet_hospital_mcp/tools/` 新增一个模块，实现 `register(server, client)` 和 `INPUT_MODEL`；`tools/__init__.py` 会自动发现（跳过下划线开头的模块）。不改 `rest_client.py` 已有方法的签名、不改 `errors.py`、不改 `logging_config.py`、不改 `server.py`。
   - 需要新的上游调用 → 在 `rest_client.py` 里参照 `_fetch(path, params, model, what)` 加一个一行方法，**不要**复制「取数 → 判状态 → 解析信封 → 校验 data」这套流程。
   - 需要新的出参模型 → 加到 `src/pet_hospital_mcp/upstream.py`，配置用 `UPSTREAM_CONFIG`（`extra="allow", strict=True`）。
   - 需要新的共享入参（如「按 id + 日期区间」）→ 加到 `tools/_shared.py`。
2. **严格入参**：新增一个 `BaseModel`，`ConfigDict(extra="forbid", strict=True)`；枚举取值**必须来自 Go 侧 `internal/model/model.go` / `internal/api/api.go` 的真实允许值**（可以先 `curl http://127.0.0.1:8080/api/v1/meta` 核对），不许自己编；数值加 `ge`/`le`；不要依赖隐式强转。
3. **统一错误**：所有失败必须走 `errors.failure(...)` / `ToolFailure`，返回 `{"error":{"code","message","details"}}`；错误码只能从已有的 6 个里选。上游 404 映射为 `BACKEND_API_ERROR` 并把 `details.status = 404` 带上（这是现有约定，见 README 第 9 节）。
4. **统一日志**：日志点**已经**由 `ContractMiddleware` 统一负责，工具里**不要**再打点。字段保持 `timestamp / tool_name / params / status / duration_ms`，`params` 走递归脱敏。
5. **描述可读**：`TOOL_DESCRIPTION` 按现有工具的格式写，必须有【用途】【适用场景】【不适用】【参数】【返回值】【错误码】六段（`test_tool_schema.py` 会逐个体检）。
6. **出参强类型**：为成功响应建 Pydantic 模型。注意 Go 把 `0.0` 序列化成 `0`（整数），Pydantic 严格模式下 `int` → `float` 是无损转换、会被接受，**不要**为了这个把出参模型改成宽松模式。
7. **测试齐备**：在 `tests/` 补测试，至少覆盖
   - 上游路径与参数转发正确（用 `httpx.MockTransport` 断言 URL 与查询串）；
   - 各枚举/区间越界、未知字段、类型错误 → `VALIDATION_ERROR` + 统一信封；
   - 上游 4xx / 5xx / 超时 / 连接失败 / 坏 JSON / 坏模型 → 对应错误码；
   - 工具已注册、名称正确、JSON Schema 含枚举与边界、`additionalProperties: false`（经 HTTP `tools/list` 断言）；
   - **校验按工具名路由**：把 A 工具的参数发给 B 工具必须被拒；
   - 不泄漏 Pydantic/SDK 原文。
8. **更新工具集清单**：新工具会让 `tests/helpers.py` 里的 `EXPECTED_TOOLS` 失效，先改它，再改 `test_tool_schema.py`。
9. **不回归**：`cd pet-hospital-mcp && pytest -q` 必须全绿（当前基线：`282 passed`）。

---

## 三、验收方式

交付时请自行完成并给出真实结果：

```bash
cd pet-hospital-mcp

# 1) 测试
pytest -q

# 2) 起真实服务做端到端验收（需先启动 pethospital.exe）
python -m pet_hospital_mcp
python _e2e_check.py          # 或按 README 第 11 节的 curl / SDK 片段手工验证
python _sdk_check.py
```

需要报告：

- 新增/修改的文件清单；
- `pytest -q` 的真实输出；
- 至少一个新工具的真实调用请求与响应（含一次成功的、一次 `VALIDATION_ERROR` 的）；
- 明确声明**仍未实现**的工具范围。

---

## 四、风格约定

- 注释、文档、工具描述、错误信息一律用**中文**；代码标识符用英文。
- 注释解释「为什么」，不解释「是什么」；不写 `# 设置变量 x` 这类废话。
- 提交前自查：有没有可能把敏感字段（`ownerPhone` / `ownerAddr` / `chipNo`）写进日志或错误 `details`？
- 上游行为有怪异之处（如 `totalCost` 浮点末位抖动、`top-spenders` 的 `total` 语义），**不要粉饰**，要么原样透传并在 README 里记一笔，要么明确说明为什么不做成工具。
