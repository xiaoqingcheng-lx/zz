你是一位精通 Model Context Protocol（MCP）和 Python 的专家开发者。请在当前仓库中 `pet-hospital-mcp/` 目录，从零开发一个独立的 MCP 服务，用于将现有 Go 宠物医院 REST API 的能力暴露给 AI Agent。

开始前，请阅读并理解：

1. 仓库根目录的 Go 宠物医院 REST API；
2. README、数据模型和 `GET /api/v1/pets` 的真实接口定义；
3. 官方 Python SDK 2.x 文档及 MCP 2026-07-28 规范。

本项目不需要实现、兼容或迁移 SDK 1.x 的 FastMCP 服务。

## 技术目标

新建一个满足以下要求的 MCP 服务：

- Python 3.11+
- 官方 Python SDK `mcp==2.0.0`
- MCP 协议版本 `2026-07-28`
- SDK 2.x 的 `MCPServer`
- 无状态 Streamable HTTP 模型
- 不得使用或导入 `mcp.server.fastmcp.FastMCP`
- 不得实现旧协议的 `initialize`、`Mcp-Session-Id`、会话存储、会话过期、`max_sessions` 或有状态 SSE 恢复机制

开始编码前，先查阅官方 Python SDK 2.x 文档和 MCP 2026-07-28 协议文档，确认 `MCPServer`、HTTP 应用装配、路由、工具注册、工具调用结果、`server/discover` 和 Streamable HTTP 的实际 API。不要凭旧版 FastMCP 经验猜测新 API。

## 现有系统边界

- 现有 Go 宠物医院服务是唯一业务后端，不得修改它。
- MCP 服务必须是独立 Python 服务，只能通过 HTTP 调用 Go REST API。
- 上游地址由 `PET_HOSPITAL_BASE_URL` 配置，默认：
  `http://127.0.0.1:8080`
- MCP 默认只监听 `127.0.0.1`。
- `MCP_HOST`、`MCP_PORT` 必须可配置。
- 保留 `/health` 健康检查端点。
- 教学场景不实现认证、权限、CORS 或 Origin 校验。
- 不要自行开始阶段二；本次仍只保留一个 MCP 工具。

## 本次唯一工具

只实现：

```text
list_pets
```

它必须严格适配现有 Go REST API：

```text
GET /api/v1/pets
```

支持且仅支持以下查询参数：

```text
q
name
ownerName
ownerPhone
species
doctor
disease
status
min
max
sortBy
order
page
pageSize
```

要求：

- 工具名使用 `snake_case`。
- 不新增适配器私有业务参数。
- 使用 Pydantic 定义输入、成功输出和错误输出模型。
- 输入模型必须严格校验：
  - `species`、`status`、`sortBy`、`order` 使用真实后端允许值；
  - `page >= 1`；
  - `1 <= pageSize <= 500`；
  - `min`、`max` 非负；
  - `min <= max`；
  - 拒绝未知字段、NaN、Infinity 和类型不正确的输入。
- 成功输出必须对应 Go API 成功响应中的 `data`：
  `items`、`total`、`page`、`pageSize`、`totalPages`、`totalCost`。
- 必须兼容 Go 的 `records`、`charges` 可能是 `null` 或数组的真实 JSON 表现。
- 工具描述必须说明用途、参数、适用场景和返回值。

## 错误处理

沿用统一结构化错误格式：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "可读错误信息",
    "details": {}
  }
}
```

至少区分：

```text
VALIDATION_ERROR
BACKEND_TIMEOUT
BACKEND_UNAVAILABLE
BACKEND_API_ERROR
BACKEND_INVALID_RESPONSE
INTERNAL_ERROR
```

要求：

- 后端调用必须有超时和有限重试。
- 不得把 HTTPX、Pydantic、SDK 或 Python 堆栈原样暴露给 MCP 客户端。
- 按 SDK 2.x 实际规定，正确标记工具调用失败状态；不要沿用 1.x 的 `CallToolResult.isError` 写法，除非官方 2.x 文档明确仍采用该机制。
- 所有无效工具输入和上游异常都必须返回统一错误结构。

## 模块结构

保持或优化为清晰、可扩展的结构，例如：

```text
pet_hospital_mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── server.py
│       ├── rest_client.py
│       ├── errors.py
│       ├── logging_config.py
│       └── tools/
│           ├── __init__.py
│           └── list_pets.py
└── tests/
```

后续阶段新增工具时，应只需在 `tools/` 增加模块并复用 REST 客户端、日志和错误约定。

## 依赖与日志

- 使用 `pyproject.toml`。
- 固定 `mcp==2.0.0`。
- 使用 `httpx`。
- 使用 Pydantic。
- 使用标准库 JSON logging 或 `structlog`。
- 日志至少包含：
  `timestamp`、`tool_name`、`params`、`status`、`duration_ms`。
- `ownerPhone`、`ownerAddr`、`chipNo` 及其 snake_case 写法必须在日志中递归脱敏。
- 不要把完整敏感数据写入日志。

## 测试

使用：

```text
pytest
pytest-asyncio
httpx.MockTransport 或 respx
```

禁止测试时访问真实 Go 服务。

至少覆盖：

1. 正常调用：确认请求路径和全部过滤/排序/分页参数正确转发；
2. 输入参数校验失败；
3. Go REST API 返回 4xx/5xx；
4. 超时和连接异常；
5. 后端返回非法 JSON 或不符合数据模型；
6. MCP 工具注册、工具名和 JSON Schema；
7. SDK 2.x 的无状态连接流程：
   - 不发送旧 `initialize`；
   - 不要求或返回 `Mcp-Session-Id`；
   - 使用 2026-07-28 实际规定的发现/调用方式；
   - 验证 `/health`；
   - 验证工具可通过 HTTP MCP 端点被发现和调用。

运行命令必须是：

```bash
cd pet_hospital_mcp
pytest -q
```

确保测试全部通过。

## README 撰写要求

README 必须明确说明：

- 安装与启动命令；
- Go REST API 必须先启动；
- `MCP_HOST`、`MCP_PORT`、`PET_HOSPITAL_BASE_URL`；
- MCP 端点；
- 实际 SDK 版本；
- 实际协议版本；
- 使用 `MCPServer`；
- MCP Inspector 或 SDK 2.x 客户端的验证步骤；
- `list_pets` 调用示例；
- `/health` 示例；
- 单元测试命令和预期结果。

## 最终交付

完成后请输出：

1. 修改后的目录结构；
2. 实际修改的文件列表；
3. 测试命令和真实测试结果；
4. 如何启动 Go 服务和 MCP 服务；
5. 如何验证无状态 MCP 连接和调用 `list_pets`；
6. 明确声明：未实现阶段二工具。