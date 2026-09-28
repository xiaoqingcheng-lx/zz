# 🐾 宠物医院 · Pet Hospital REST API

一个用 **Go 标准库** 编写的本地宠物医院管理系统。启动后在本地开启 HTTP 服务：
浏览器打开根路径即是**网页操作界面**，同时提供完整的 REST 接口
（查询 / 新增 / 删除 / 批量 / 导出 / 统计），**无鉴权、无登录**，
数据存储在**单个本地文件**中。

> **一句话记住**：复制「可执行文件 + `data/pet.db`」到另一台电脑，双击即可继续使用，
> 无需安装 Go、数据库或任何运行时依赖。

## 特性

- **网页操作界面**：浏览器访问 `http://127.0.0.1:8080/` 即可增删改查，无需写代码
  - 档案列表、关键词搜索、按种类/医生/状态筛选、排序、分页
  - 新增 / 编辑 / 删除档案（带表单校验与错误提示）
  - 点开档案查看**历史病历**与**消费明细**，以及费用汇总
  - 顶部实时展示档案数、病历数、收费笔数、总收入、客单价
  - **网页已内嵌进可执行文件**，不需要额外的 html/css/js 文件
- **单文件可迁移**：只需 `可执行文件` + `data/pet.db` 两个文件即可搬迁到任何电脑
- **零第三方依赖**：只用 Go 标准库，`go build` 即可，无需联网拉包
- **单文件数据库**：`data/pet.db`，自行实现的嵌入式存储引擎
  - 追加写日志（append-only）+ CRC32 校验 + 内存索引
  - 自动压实（compaction）回收日志垃圾
  - 崩溃安全：原子重写（写临时文件后 `rename`）、`fsync` 落盘
  - 损坏自愈：断电导致的半条记录会被检测并自动截断修复
- **无鉴权**：直接调用，适合本地开发、演示、教学
- **启动即导航**：终端打印网页入口 + 全部服务清单 + 可复制的访问案例，随后实时打印访问日志

## 快速开始

### 方式一：直接使用已编译好的发行包（推荐）

请从本仓库的 [GitHub Releases](../../releases) 下载与你的系统匹配的发行 ZIP。解压后结构如下：

```text
pet-hospital-windows-amd64/
├── pethospital.exe     ← 可执行文件（已内嵌网页）
├── README.md           ← 本说明
└── data/
    └── pet.db          ← 测试数据库（含模拟数据，可直接打开体验）
```

```bash
cd pet-hospital-windows-amd64
pethospital.exe                       # Windows（双击或命令行）
```

然后浏览器打开 <http://127.0.0.1:8080/> 即可看到界面。

> Windows 程序会在终端打印访问地址，**不会自动打开浏览器**。其他平台请下载对应发行包，或用「方式二」自行编译。

### 方式二：从源码编译

```bash
# 编译到 dist 目录（推荐，与发行包结构一致）
make dist            # 或： ./build.sh

# 或者直接运行源码
go run .                                  # 默认 127.0.0.1:8080，数据文件 ./data/pet.db
go run . -seed                            # 首次启动写入 8 条手工精选数据
go run . -seed -count 2000                # 写入 8 条手工 + 2000 条随机模拟数据
go run . -addr :9090 -db /tmp/hospital.db # 自定义端口与数据库路径
go run . -no-color                        # 关闭彩色输出
```

### 交叉编译到其他平台

```bash
GOOS=windows GOARCH=amd64 go build -o dist/pethospital.exe .   # Windows 64 位
GOOS=linux   GOARCH=amd64 go build -o dist/pethospital-linux . # Linux 64 位
GOOS=darwin  GOARCH=arm64 go build -o dist/pethospital .       # macOS Apple Silicon
GOOS=darwin  GOARCH=amd64 go build -o dist/pethospital-intel . # macOS Intel
```

启动后终端会显示：

```text
╔═══════════════════════════════════════════════════════════╗
║          🐾  宠 物 医 院 · Pet Hospital REST API  🐾       ║
║           宠物 / 主人 / 电话 / 疾病 / 医生 / 历史病历 / 总花费   ║
╚═══════════════════════════════════════════════════════════╝
  版本 1.0.0   数据库 data/pet.db   现有档案 308 条

▍网页操作界面

  在浏览器中打开：
    http://127.0.0.1:8080/

  提供：档案列表与搜索、新增/编辑/删除档案、查看历史病历与消费明细、经营统计
  网页资源已内嵌到可执行文件中，无需额外的 html/css/js 文件

▍服务清单（共 29 个接口）
...

  ✅ 服务已启动，请访问：  http://127.0.0.1:8080/
    接口清单（JSON）：  http://127.0.0.1:8080/api/v1/endpoints
    数据库文件：  data/pet.db

▍实时访问日志（Ctrl+C 退出）

│ 12:12:02 ✅ 200  GET /health 182 B 87µs
│ 12:12:02 ⚠️  404  GET /api/v1/pets/PET-999999 91 B 60µs
```

## 网页操作界面

浏览器打开 `http://127.0.0.1:8080/` 即可，**不需要写任何代码或命令**：

| 功能 | 位置 | 对应接口 |
| --- | --- | --- |
| 查看档案列表（搜索 / 筛选 / 排序 / 分页） | 首页表格 | `GET /api/v1/pets` |
| 新增档案 | 右上角「+ 新增档案」 | `POST /api/v1/pets` |
| 编辑 / 删除档案 | 每行「编辑」按钮 | `PUT` / `DELETE /api/v1/pets/{id}` |
| 查看历史病历 + 消费明细 + 费用汇总 | 点击表格任意一行 | `GET /api/v1/pets/{id}` + `/summary` |
| 经营统计（档案数 / 总收入 / 客单价…） | 页面顶部卡片 | `GET /api/v1/stats` |

界面为单页应用，使用系统原生字体与响应式布局，手机浏览器也可使用。
所有用户数据经浏览器原生 `textContent` 渲染，天然避免 XSS。

## 迁移到其他电脑

发行包只需两个文件，复制到同一个目录即可：

```text
任意目录/
├── pethospital      ← 可执行文件（已内嵌网页）
└── data/
    └── pet.db       ← 数据库文件（全部数据）
```

然后在该目录下运行：

```bash
./pethospital                 # macOS / Linux
pethospital.exe               # Windows（双击或命令行）
```

**目标电脑无需安装 Go、数据库或任何依赖。** 注意：

- 若目标目录没有 `data/pet.db`，程序会**自动新建**一个空库（可用 `-seed` 灌入演示数据）
- `pet.db` 是全部数据所在，请**定期备份**；程序运行时也可直接复制它
- 可执行文件需与目标系统架构匹配（见上方「交叉编译」）

## 数据模型

主档 `Pet` 包含：宠物姓名、种类、品种、性别、月龄、毛色、芯片号、
主人姓名、电话、住址、主治医生、疾病、就诊状态、过敏史，
以及 **历史病历 `records[]`** 与 **消费明细 `charges[]`**。

派生字段（只读，自动汇总）：

| 字段 | 说明 |
| --- | --- |
| `totalCost` | 在医院总花费金额 = `charges[].amount` 之和 |
| `visitCount` | 就诊次数 = `records` 条数 |

## 接口一览

统一响应信封：

```json
{ "code": 200, "message": "ok", "data": { }, "time": "2025-01-01T00:00:00+08:00" }
```

### 系统与统计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | **网页操作界面**（浏览器打开即可使用） |
| GET | `/health` | 健康检查 |
| GET | `/api/v1/endpoints` | 接口清单（JSON，机器可读） |
| GET | `/api/v1/meta` | 枚举字典与字段说明 |
| GET | `/api/v1/stats` | 经营统计（收入 / 种类 / 医生排行） |

### 宠物档案 CRUD

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/pets` | 列表：过滤 + 排序 + 分页 |
| POST | `/api/v1/pets` | 新增（`id` 自动生成 `PET-000001`） |
| GET | `/api/v1/pets/{id}` | 按 ID 查询 |
| PUT | `/api/v1/pets/{id}` | 全量更新（未传字段会清空） |
| PATCH | `/api/v1/pets/{id}` | 局部更新（只改传入字段） |
| DELETE | `/api/v1/pets/{id}` | 删除 |

### 高级查询

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/pets/search?q=` | 全文检索（跨字段，空格分词 AND，含病历全文） |
| GET | `/api/v1/pets/by-owner?ownerName=&phone=` | 按主人姓名 / 电话 |
| GET | `/api/v1/pets/by-doctor?doctor=` | 按医生 |
| GET | `/api/v1/pets/by-species?species=` | 按种类 |
| GET | `/api/v1/pets/by-disease?disease=` | 按疾病 |
| GET | `/api/v1/pets/by-status?status=` | 按就诊状态 |
| GET | `/api/v1/pets/top-spenders?limit=` | 消费排行榜 |
| GET | `/api/v1/pets/cost-range?min=&max=` | 按总花费区间 |

### 历史病历 / 消费明细

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/pets/{id}/records` | 查询历史病历 |
| POST | `/api/v1/pets/{id}/records` | 追加一条病历 |
| GET | `/api/v1/pets/{id}/charges` | 查询消费明细 |
| POST | `/api/v1/pets/{id}/charges` | 追加一笔收费（自动累计总花费） |
| GET | `/api/v1/pets/{id}/summary` | 单只宠物费用与就诊汇总 |

### 批量 / 导出 / 管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/pets/batch` | 批量新增 |
| POST | `/api/v1/pets/batch-delete` | 批量删除 |
| GET | `/api/v1/export?format=json\|csv` | 导出全部数据 |
| POST | `/api/v1/admin/compact` | 手动压实数据库文件 |
| POST | `/api/v1/admin/seed?force=true&count=N` | 写入模拟数据（`count=all` 为 1000 条） |

## 模拟数据

内置一个**可复现**的模拟数据生成器（固定随机种子，多次运行结果一致），
覆盖 17 个字段维度、46 种真实兽医疾病、12 位医生、7 个种类、全国 10 个城市。

```bash
# 启动时生成
go run . -seed -count 2000        # 8 条手工精选 + 2000 条随机

# 服务运行中追加
curl -s -X POST 'http://127.0.0.1:8080/api/v1/admin/seed?force=true&count=1000'
curl -s -X POST 'http://127.0.0.1:8080/api/v1/admin/seed?force=true&count=all'
```

生成的数据遵循真实兽医业务规律：

- **疾病与物种匹配**：不会出现「仓鼠股骨骨折」「鹦鹉犬瘟热」这类不合常理的组合
- **医生分配按专长**：骨科病例分给骨科医生，皮肤病分给皮肤科医生
- **费用分层合理**：按疾病大类（手术/检查/药品/住院/疫苗/护理/其他）选取收费项，
  重症费用高、复查费用递减
- **多次就诊**：重症患者有 2-5 次随访记录，形成完整的「历史病历」
- **状态自动推断**：依据疾病严重度与最后就诊时间推断待就诊/就诊中/住院中/已康复/慢性病随访
- **20% 宠物未植入芯片**，5% 有备注，过敏史按真实比例分布（多数为「无」）

实测规模参考（2000 条）：约 4294 条病历、17201 笔收费、4.6MB 数据库文件，
写入耗时约 1.5 秒。

## 列表查询参数

`/api/v1/pets` 支持：`q` `name` `ownerName` `ownerPhone` `species` `doctor`
`disease` `status` `min` `max` `sortBy` `order` `page` `pageSize`。

```bash
curl -s 'http://127.0.0.1:8080/api/v1/pets?species=犬&min=1000&sortBy=totalCost&order=desc&page=1&pageSize=10'
```

## 使用示例

```bash
# 新增宠物
curl -s -X POST http://127.0.0.1:8080/api/v1/pets \
  -H 'Content-Type: application/json' -d '{
    "name":"旺财","species":"犬","breed":"金毛","gender":"公","ageMonths":36,
    "ownerName":"张三","ownerPhone":"13800001111",
    "disease":"急性肠胃炎","doctor":"李医生","status":"待就诊"
  }'

# 追加病历
curl -s -X POST http://127.0.0.1:8080/api/v1/pets/PET-000001/records \
  -H 'Content-Type: application/json' -d '{
    "doctor":"李医生","diagnosis":"急性肠胃炎","symptoms":"呕吐腹泻",
    "treatment":"补液消炎","prescription":["阿莫西林"],"charge":380
  }'

# 追加收费（总花费自动累计）
curl -s -X POST http://127.0.0.1:8080/api/v1/pets/PET-000001/charges \
  -H 'Content-Type: application/json' -d '{"item":"血常规检查","category":"检查","amount":180,"doctor":"李医生"}'

# 全文检索病历
curl -s 'http://127.0.0.1:8080/api/v1/pets/search?q=肠胃炎'

# 消费排行榜
curl -s 'http://127.0.0.1:8080/api/v1/pets/top-spenders?limit=5'

# 导出 CSV
curl -s 'http://127.0.0.1:8080/api/v1/export?format=csv' -o pets.csv

# 删除
curl -s -X DELETE http://127.0.0.1:8080/api/v1/pets/PET-000001
```

## 项目结构

```text
.
├── main.go                  启动横幅、服务网址、优雅退出
├── go.mod
├── Makefile                 构建与发行命令（make help）
├── build.sh                 构建脚本（无需 make）
└── internal/
    ├── model/model.go       数据模型与校验
    ├── store/store.go       单文件嵌入式数据库引擎
    └── api/
        ├── api.go           REST 路由与处理器
        ├── generate.go      大批量模拟数据生成器
        ├── support.go       ANSI 着色、手工精选数据
        ├── web.go           网页路由（embed 内嵌）
        └── web/index.html   网页界面（单文件）
```

## 构建与发布

```bash
make help          # 查看全部命令
make build         # 编译到 dist/pethospital
make dist          # 构建 + 准备测试数据库 + 拷贝说明文档
make test-db       # 仅重建测试数据库（dist/data/pet.db，1000 条模拟数据）
make clean         # 清理构建产物
```

`make dist` 产出的 `dist/` 可作为 Release ZIP 的内容：可执行文件、`data/pet.db` 和 `README.md` 必须保持同一目录结构。项目根目录下的 `build.sh` 提供等价功能，不依赖 `make`。

发布时请将 ZIP 作为 GitHub Release 附件上传；`dist/` 是本地构建产物，不提交到仓库。

## 数据库文件格式

```text
┌ Header 32B ─────────────────────────────────┐
│ magic "PETDBv1\n" | version u32 | flags u32 │
├ Record 记录区（顺序追加）───────────────────┤
│ [len u32][crc32 u32][json payload]          │
│ payload: {"op":"put|del","id":"...","data":{}} │
└─────────────────────────────────────────────┘
```

- **读**：启动时回放日志，重建内存 map 索引
- **写**：追加一条记录 + `fsync`，同步更新索引
  - 写入位置在内存中维护（`WriteAt` 定位写），避免每条记录都 `Seek` 到文件尾
  - 批量写入（`CreateManyCount`）每 500 条才 `fsync` 一次
- **压实**：垃圾超过阈值时原子重写文件（`pet.db.tmp` → `rename`）
- **恢复**：CRC 校验失败或长度异常时截断到最后一个完整记录

## 说明

- 明文 HTTP、无鉴权，**仅适用于本地/内网**，请勿直接暴露到公网
- `PUT` 是全量替换语义，未携带的字段（含 `records`/`charges`）会被清空；
  仅想改部分字段请用 `PATCH`
- `-seed` 只在数据库为空时生效，不会重复写入；服务运行中可用
  `POST /api/v1/admin/seed?force=true&count=N` 强制追加
- Go 版本要求：**1.22+**（使用了增强型 `ServeMux` 路由）
