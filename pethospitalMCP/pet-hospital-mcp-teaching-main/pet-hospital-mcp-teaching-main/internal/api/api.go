// Package api 提供宠物医院的 REST 服务。
//
// 全部基于 net/http 标准库：
//   - Go 1.22+ 的增强型 ServeMux 支持 "METHOD /path/{id}" 路由
//   - 无鉴权、无登录，直接可用
//   - 统一 JSON 响应信封 { "code":0, "message":"ok", "data":... }
package api

import (
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"net/http"
	"strconv"
	"strings"
	"time"

	"pethospital/internal/model"
	"pethospital/internal/store"
)

// ---------------------------------------------------------------------------
// 响应信封
// ---------------------------------------------------------------------------

// Resp 统一响应结构。
type Resp struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
	Time    string `json:"time"`
}

// Endpoint 描述一个对外暴露的服务（用于启动横幅打印）。
type Endpoint struct {
	Method  string
	Path    string
	Desc    string
	Example string
}

// Endpoints 返回全部服务清单（启动时打印到终端）。
func Endpoints() []Endpoint {
	return []Endpoint{
		// ---------- 系统 ----------
		{"GET", "/", "网页操作界面（浏览器打开即可使用）", `# 在浏览器中打开 http://HOST/`},
		{"GET", "/health", "健康检查", `curl -s http://HOST/health`},
		{"GET", "/api/v1/endpoints", "接口清单（机器可读）", `curl -s http://HOST/api/v1/endpoints`},
		{"GET", "/api/v1/stats", "医院经营统计（收入/种类/医生排行）", `curl -s 'http://HOST/api/v1/stats?top=5'`},
		{"GET", "/api/v1/meta", "枚举字典（种类/状态/收费分类）", `curl -s http://HOST/api/v1/meta`},

		// ---------- 宠物档案 CRUD ----------
		{"GET", "/api/v1/pets", "查询宠物列表（过滤+排序+分页）", `curl -s 'http://HOST/api/v1/pets?species=犬&page=1&pageSize=10'`},
		{"POST", "/api/v1/pets", "新增宠物档案", `curl -s -X POST http://HOST/api/v1/pets -H 'Content-Type: application/json' -d '{"name":"旺财","species":"犬","ownerName":"张三","ownerPhone":"13800001111","disease":"急性肠胃炎","doctor":"李医生"}'`},
		{"GET", "/api/v1/pets/{id}", "按 ID 查询单个宠物", `curl -s http://HOST/api/v1/pets/PET-000001`},
		{"PUT", "/api/v1/pets/{id}", "全量更新宠物档案", `curl -s -X PUT http://HOST/api/v1/pets/PET-000001 -H 'Content-Type: application/json' -d '{"name":"旺财","species":"犬","ownerName":"张三","ownerPhone":"13800001111","disease":"已康复","doctor":"李医生","status":"已康复"}'`},
		{"PATCH", "/api/v1/pets/{id}", "局部更新（只传要改的字段）", `curl -s -X PATCH http://HOST/api/v1/pets/PET-000001 -H 'Content-Type: application/json' -d '{"status":"住院中","doctor":"王医生"}'`},
		{"DELETE", "/api/v1/pets/{id}", "删除宠物档案", `curl -s -X DELETE http://HOST/api/v1/pets/PET-000001`},

		// ---------- 搜索 / 高级查询 ----------
		{"GET", "/api/v1/pets/search", "全文检索（跨字段，空格分词 AND）", `curl -s 'http://HOST/api/v1/pets/search?q=肠胃炎'`},
		{"GET", "/api/v1/pets/by-owner", "按主人姓名/电话查宠物", `curl -s 'http://HOST/api/v1/pets/by-owner?ownerName=张三'`},
		{"GET", "/api/v1/pets/by-doctor", "按医生查其接诊的宠物", `curl -s 'http://HOST/api/v1/pets/by-doctor?doctor=李医生'`},
		{"GET", "/api/v1/pets/by-species", "按种类查宠物", `curl -s 'http://HOST/api/v1/pets/by-species?species=猫'`},
		{"GET", "/api/v1/pets/by-disease", "按疾病查宠物", `curl -s 'http://HOST/api/v1/pets/by-disease?disease=骨折'`},
		{"GET", "/api/v1/pets/by-status", "按就诊状态查宠物", `curl -s 'http://HOST/api/v1/pets/by-status?status=住院中'`},
		{"GET", "/api/v1/pets/top-spenders", "消费排行榜（在医院总花费）", `curl -s 'http://HOST/api/v1/pets/top-spenders?limit=5'`},
		{"GET", "/api/v1/pets/cost-range", "按总花费区间查询", `curl -s 'http://HOST/api/v1/pets/cost-range?min=500&max=5000'`},

		// ---------- 历史病历 ----------
		{"GET", "/api/v1/pets/{id}/records", "查询某宠物的历史病历", `curl -s http://HOST/api/v1/pets/PET-000001/records`},
		{"POST", "/api/v1/pets/{id}/records", "为宠物追加一条病历", `curl -s -X POST http://HOST/api/v1/pets/PET-000001/records -H 'Content-Type: application/json' -d '{"doctor":"李医生","diagnosis":"急性肠胃炎","symptoms":"呕吐、腹泻","treatment":"补液+消炎","prescription":["阿莫西林","蒙脱石散"],"weightKg":12.5,"temperature":39.1,"charge":380}'`},

		// ---------- 消费明细 ----------
		{"GET", "/api/v1/pets/{id}/charges", "查询某宠物的消费明细", `curl -s http://HOST/api/v1/pets/PET-000001/charges`},
		{"POST", "/api/v1/pets/{id}/charges", "为宠物追加一笔收费", `curl -s -X POST http://HOST/api/v1/pets/PET-000001/charges -H 'Content-Type: application/json' -d '{"item":"血常规检查","category":"检查","amount":180,"doctor":"李医生"}'`},
		{"GET", "/api/v1/pets/{id}/summary", "单只宠物费用与就诊汇总", `curl -s http://HOST/api/v1/pets/PET-000001/summary`},

		// ---------- 批量 / 导入导出 ----------
		{"POST", "/api/v1/pets/batch", "批量新增（一次多条）", `curl -s -X POST http://HOST/api/v1/pets/batch -H 'Content-Type: application/json' -d '[{"name":"咪咪","species":"猫","ownerName":"李四","ownerPhone":"13900002222","disease":"猫瘟","doctor":"王医生"}]'`},
		{"POST", "/api/v1/pets/batch-delete", "批量删除", `curl -s -X POST http://HOST/api/v1/pets/batch-delete -H 'Content-Type: application/json' -d '{"ids":["PET-000002","PET-000003"]}'`},
		{"GET", "/api/v1/export", "导出全部数据（json / csv）", `curl -s 'http://HOST/api/v1/export?format=csv' -o pets.csv`},
		{"POST", "/api/v1/admin/compact", "手动压实数据库文件（清理日志垃圾）", `curl -s -X POST http://HOST/api/v1/admin/compact`},
		{"POST", "/api/v1/admin/seed", "写入模拟数据（可选 count=N 或 all）", `curl -s -X POST 'http://HOST/api/v1/admin/seed?force=true&count=1000'`},
	}
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------

// Server REST 服务。
type Server struct {
	db    *store.Store
	mux   *http.ServeMux
	Logf  func(format string, args ...any) // 请求日志回调（由 main 注入）
	start time.Time
}

// New 构造服务并注册全部路由。
func New(db *store.Store, logf func(string, ...any)) *Server {
	if logf == nil {
		logf = func(string, ...any) {}
	}
	s := &Server{db: db, mux: http.NewServeMux(), Logf: logf, start: time.Now()}
	s.routes()
	return s
}

// Handler 返回 http.Handler（已带日志中间件）。
func (s *Server) Handler() http.Handler { return s.logMiddleware(s.mux) }

func (s *Server) routes() {
	m := s.mux

	m.HandleFunc("GET /api/v1/endpoints", s.handleEndpoints)
	m.HandleFunc("GET /health", s.handleHealth)
	m.HandleFunc("GET /api/v1/meta", s.handleMeta)
	m.HandleFunc("GET /api/v1/stats", s.handleStats)

	// 注意：更具体的路径必须注册，ServeMux 会自动优先匹配更具体的模式。
	m.HandleFunc("GET /api/v1/pets", s.handleList)
	m.HandleFunc("POST /api/v1/pets", s.handleCreate)
	m.HandleFunc("GET /api/v1/pets/search", s.handleSearch)
	m.HandleFunc("GET /api/v1/pets/by-owner", s.handleByOwner)
	m.HandleFunc("GET /api/v1/pets/by-doctor", s.handleByDoctor)
	m.HandleFunc("GET /api/v1/pets/by-species", s.handleBySpecies)
	m.HandleFunc("GET /api/v1/pets/by-disease", s.handleByDisease)
	m.HandleFunc("GET /api/v1/pets/by-status", s.handleByStatus)
	m.HandleFunc("GET /api/v1/pets/top-spenders", s.handleTopSpenders)
	m.HandleFunc("GET /api/v1/pets/cost-range", s.handleCostRange)
	m.HandleFunc("GET /api/v1/pets/{id}", s.handleGet)
	m.HandleFunc("PUT /api/v1/pets/{id}", s.handleUpdate)
	m.HandleFunc("PATCH /api/v1/pets/{id}", s.handlePatch)
	m.HandleFunc("DELETE /api/v1/pets/{id}", s.handleDelete)
	m.HandleFunc("GET /api/v1/pets/{id}/records", s.handleGetRecords)
	m.HandleFunc("POST /api/v1/pets/{id}/records", s.handleAddRecord)
	m.HandleFunc("GET /api/v1/pets/{id}/charges", s.handleGetCharges)
	m.HandleFunc("POST /api/v1/pets/{id}/charges", s.handleAddCharge)
	m.HandleFunc("GET /api/v1/pets/{id}/summary", s.handleSummary)

	m.HandleFunc("POST /api/v1/pets/batch", s.handleBatchCreate)
	m.HandleFunc("POST /api/v1/pets/batch-delete", s.handleBatchDelete)
	m.HandleFunc("GET /api/v1/export", s.handleExport)
	m.HandleFunc("POST /api/v1/admin/compact", s.handleCompact)
	m.HandleFunc("POST /api/v1/admin/seed", s.handleSeed)

	// 网页界面（嵌入二进制）：浏览器访问根路径即可
	s.registerWeb()

	// 兜底 404（浏览器请求返回 HTML 提示，API 请求返回 JSON）
	m.HandleFunc("/", s.handleNotFound)
}

// ---------------------------------------------------------------------------
// 中间件：请求日志
// ---------------------------------------------------------------------------

type statusWriter struct {
	http.ResponseWriter
	code int
	size int
}

func (w *statusWriter) WriteHeader(code int) {
	w.code = code
	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	if w.code == 0 {
		w.code = http.StatusOK
	}
	n, err := w.ResponseWriter.Write(b)
	w.size += n
	return n, err
}

func (s *Server) logMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w}
		next.ServeHTTP(sw, r)
		if sw.code == 0 {
			sw.code = http.StatusOK
		}
		q := r.URL.RawQuery
		if q != "" {
			q = "?" + q
		}
		icon := "✅"
		switch {
		case sw.code >= 500:
			icon = "💥"
		case sw.code >= 400:
			icon = "⚠️ "
		}
		s.Logf("%s %s %s%-4d%s %s %s%s %d B %s",
			time.Now().Format("15:04:05"),
			icon,
			colorFor(sw.code), sw.code, "\x1b[0m",
			r.Method, r.URL.Path, dim(q),
			sw.size,
			time.Since(start).Round(time.Microsecond),
		)
	})
}

// ---------------------------------------------------------------------------
// 基础工具
// ---------------------------------------------------------------------------

func (s *Server) writeJSON(w http.ResponseWriter, code int, data any, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(Resp{
		Code:    code,
		Message: msg,
		Data:    data,
		Time:    model.NowString(),
	})
}

func (s *Server) ok(w http.ResponseWriter, data any) { s.writeJSON(w, http.StatusOK, data, "ok") }

func (s *Server) fail(w http.ResponseWriter, code int, err error) {
	s.writeJSON(w, code, nil, err.Error())
}

// statusOf 把领域错误映射为 HTTP 状态码。
func statusOf(err error) int {
	switch {
	case errors.Is(err, store.ErrNotFound):
		return http.StatusNotFound
	case errors.Is(err, store.ErrDuplicate):
		return http.StatusConflict
	default:
		return http.StatusBadRequest
	}
}

func pathID(r *http.Request) string { return r.PathValue("id") }

func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

func queryFloat(r *http.Request, key string, def float64) float64 {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return def
	}
	return f
}

// buildQuery 从 URL 参数构造列表查询条件。
func buildQuery(r *http.Request) store.Query {
	qv := r.URL.Query()
	q := store.Query{
		Search:     qv.Get("q"),
		Name:       qv.Get("name"),
		OwnerName:  qv.Get("ownerName"),
		OwnerPhone: qv.Get("ownerPhone"),
		Species:    qv.Get("species"),
		Doctor:     qv.Get("doctor"),
		Disease:    qv.Get("disease"),
		Status:     qv.Get("status"),
		SortBy:     qv.Get("sortBy"),
		Order:      qv.Get("order"),
		Page:       queryInt(r, "page", 1),
		PageSize:   queryInt(r, "pageSize", 20),
	}
	if qv.Has("min") || qv.Has("max") {
		q.HasCost = true
		q.MinCost = queryFloat(r, "min", 0)
		q.MaxCost = queryFloat(r, "max", 1e18)
	}
	return q
}

func decodeJSON(r *http.Request, v any) error {
	defer r.Body.Close()
	dec := json.NewDecoder(http.MaxBytesReader(nil, r.Body, 32<<20))
	if err := dec.Decode(v); err != nil {
		return fmt.Errorf("请求体 JSON 解析失败: %w", err)
	}
	return nil
}

// ---------------------------------------------------------------------------
// 系统类处理器
// ---------------------------------------------------------------------------

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	s.ok(w, map[string]any{
		"status":    "healthy",
		"uptime":    time.Since(s.start).Round(time.Second).String(),
		"dbFile":    s.db.Path(),
		"petCount":  s.db.Count(),
		"timestamp": model.NowString(),
	})
}

func (s *Server) handleEndpoints(w http.ResponseWriter, r *http.Request) {
	s.ok(w, map[string]any{
		"count":     len(Endpoints()),
		"endpoints": Endpoints(),
	})
}

func (s *Server) handleMeta(w http.ResponseWriter, r *http.Request) {
	s.ok(w, map[string]any{
		"species":          model.ValidSpecies,
		"status":           model.ValidStatus,
		"chargeCategories": []string{"检查", "药品", "手术", "住院", "疫苗", "护理", "其他"},
		"sortFields":       []string{"id", "name", "ownerName", "species", "doctor", "disease", "status", "totalCost", "visitCount", "createdAt", "updatedAt"},
		"gender":           []string{"公", "母"},
		"fields": []map[string]string{
			{"name": "id", "desc": "档案编号，自动生成 PET-000001"},
			{"name": "name", "desc": "宠物姓名（必填）"},
			{"name": "species", "desc": "种类：犬/猫/兔/鸟/仓鼠/爬宠/其他"},
			{"name": "breed", "desc": "品种"},
			{"name": "gender", "desc": "性别：公/母"},
			{"name": "ageMonths", "desc": "月龄"},
			{"name": "color", "desc": "毛色"},
			{"name": "chipNo", "desc": "芯片号"},
			{"name": "ownerName", "desc": "主人姓名（必填）"},
			{"name": "ownerPhone", "desc": "主人电话（必填）"},
			{"name": "ownerAddr", "desc": "主人住址"},
			{"name": "doctor", "desc": "主治医生姓名（必填）"},
			{"name": "disease", "desc": "疾病/主要诊断（必填）"},
			{"name": "status", "desc": "就诊状态"},
			{"name": "allergy", "desc": "过敏史"},
			{"name": "note", "desc": "备注"},
			{"name": "records", "desc": "历史病历数组"},
			{"name": "charges", "desc": "消费明细数组"},
			{"name": "totalCost", "desc": "在医院总花费金额（由 charges 自动汇总，只读）"},
			{"name": "visitCount", "desc": "就诊次数（由 records 自动汇总，只读）"},
		},
	})
}

func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	s.ok(w, s.db.Stats(queryInt(r, "top", 5)))
}

// ---------------------------------------------------------------------------
// 宠物 CRUD
// ---------------------------------------------------------------------------

func (s *Server) handleList(w http.ResponseWriter, r *http.Request) {
	s.ok(w, s.db.List(buildQuery(r)))
}

func (s *Server) handleCreate(w http.ResponseWriter, r *http.Request) {
	var p model.Pet
	if err := decodeJSON(r, &p); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	p.ID = "" // 不允许客户端指定主键
	created, err := s.db.Create(&p)
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	s.writeJSON(w, http.StatusCreated, created, fmt.Sprintf("新增成功，档案编号 %s", created.ID))
}

func (s *Server) handleGet(w http.ResponseWriter, r *http.Request) {
	p, err := s.db.Get(pathID(r))
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	s.ok(w, p)
}

func (s *Server) handleUpdate(w http.ResponseWriter, r *http.Request) {
	var p model.Pet
	if err := decodeJSON(r, &p); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	updated, err := s.db.Update(pathID(r), &p)
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	s.writeJSON(w, http.StatusOK, updated, "更新成功")
}

func (s *Server) handlePatch(w http.ResponseWriter, r *http.Request) {
	raw := map[string]json.RawMessage{}
	if err := decodeJSON(r, &raw); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	buf, err := json.Marshal(raw)
	if err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	var patch model.Pet
	if err := json.Unmarshal(buf, &patch); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	fields := make(map[string]bool, len(raw))
	for k := range raw {
		fields[k] = true
	}
	updated, err := s.db.Patch(pathID(r), &patch, fields)
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	s.writeJSON(w, http.StatusOK, updated, "局部更新成功")
}

func (s *Server) handleDelete(w http.ResponseWriter, r *http.Request) {
	id := pathID(r)
	if err := s.db.Delete(id); err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	s.writeJSON(w, http.StatusOK, map[string]string{"id": id}, "删除成功")
}

// ---------------------------------------------------------------------------
// 查询类处理器
// ---------------------------------------------------------------------------

func (s *Server) handleSearch(w http.ResponseWriter, r *http.Request) {
	q := buildQuery(r)
	q.Search = r.URL.Query().Get("q")
	if q.Search == "" {
		q.Search = r.URL.Query().Get("keyword")
	}
	if q.Search == "" {
		s.fail(w, http.StatusBadRequest, errors.New("缺少查询参数 q，例如 /api/v1/pets/search?q=肠胃炎"))
		return
	}
	res := s.db.List(q)
	res.Items = highlightAll(res.Items, q.Search)
	s.ok(w, res)
}

func (s *Server) handleByOwner(w http.ResponseWriter, r *http.Request) {
	qv := r.URL.Query()
	if qv.Get("ownerName") == "" && qv.Get("phone") == "" {
		s.fail(w, http.StatusBadRequest, errors.New("需要 ownerName 或 phone 参数"))
		return
	}
	q := buildQuery(r)
	q.OwnerName = qv.Get("ownerName")
	q.OwnerPhone = qv.Get("phone")
	s.ok(w, s.db.List(q))
}

func (s *Server) handleByDoctor(w http.ResponseWriter, r *http.Request) {
	q := buildQuery(r)
	q.Doctor = r.URL.Query().Get("doctor")
	if q.Doctor == "" {
		s.fail(w, http.StatusBadRequest, errors.New("需要 doctor 参数"))
		return
	}
	s.ok(w, s.db.List(q))
}

func (s *Server) handleBySpecies(w http.ResponseWriter, r *http.Request) {
	q := buildQuery(r)
	q.Species = r.URL.Query().Get("species")
	if q.Species == "" {
		s.fail(w, http.StatusBadRequest, errors.New("需要 species 参数，取值见 /api/v1/meta"))
		return
	}
	s.ok(w, s.db.List(q))
}

func (s *Server) handleByDisease(w http.ResponseWriter, r *http.Request) {
	q := buildQuery(r)
	q.Disease = r.URL.Query().Get("disease")
	if q.Disease == "" {
		s.fail(w, http.StatusBadRequest, errors.New("需要 disease 参数"))
		return
	}
	s.ok(w, s.db.List(q))
}

func (s *Server) handleByStatus(w http.ResponseWriter, r *http.Request) {
	q := buildQuery(r)
	q.Status = r.URL.Query().Get("status")
	if q.Status == "" {
		s.fail(w, http.StatusBadRequest, errors.New("需要 status 参数，取值见 /api/v1/meta"))
		return
	}
	s.ok(w, s.db.List(q))
}

func (s *Server) handleTopSpenders(w http.ResponseWriter, r *http.Request) {
	limit := queryInt(r, "limit", 5)
	q := store.Query{SortBy: "totalCost", Order: "desc", Page: 1, PageSize: limit}
	res := s.db.List(q)
	s.ok(w, map[string]any{
		"limit":     limit,
		"items":     res.Items,
		"totalCost": res.TotalCost,
		"total":     res.Total,
	})
}

func (s *Server) handleCostRange(w http.ResponseWriter, r *http.Request) {
	q := buildQuery(r)
	q.HasCost = true
	q.MinCost = queryFloat(r, "min", 0)
	q.MaxCost = queryFloat(r, "max", 1e18)
	q.SortBy, q.Order = "totalCost", "desc"
	s.ok(w, s.db.List(q))
}

// ---------------------------------------------------------------------------
// 病历 / 收费（子资源）
// ---------------------------------------------------------------------------

func (s *Server) handleGetRecords(w http.ResponseWriter, r *http.Request) {
	p, err := s.db.Get(pathID(r))
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	recs := p.Records
	if recs == nil {
		recs = []model.MedicalRecord{}
	}
	s.ok(w, map[string]any{
		"petId":       p.ID,
		"petName":     p.Name,
		"ownerName":   p.OwnerName,
		"count":       len(recs),
		"records":     recs,
		"historyText": p.MedicalHistory(),
	})
}

func (s *Server) handleAddRecord(w http.ResponseWriter, r *http.Request) {
	var rec model.MedicalRecord
	if err := decodeJSON(r, &rec); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	if strings.TrimSpace(rec.Diagnosis) == "" {
		s.fail(w, http.StatusBadRequest, errors.New("diagnosis(诊断) 不能为空"))
		return
	}
	p, err := s.db.AddRecord(pathID(r), rec)
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	s.writeJSON(w, http.StatusCreated, p, "病历已追加")
}

func (s *Server) handleGetCharges(w http.ResponseWriter, r *http.Request) {
	p, err := s.db.Get(pathID(r))
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	charges := p.Charges
	if charges == nil {
		charges = []model.Treatment{}
	}
	byCat := map[string]float64{}
	for _, c := range charges {
		byCat[c.Category] += c.Amount
	}
	s.ok(w, map[string]any{
		"petId":          p.ID,
		"petName":        p.Name,
		"count":          len(charges),
		"charges":        charges,
		"totalCost":      p.TotalCost,
		"costByCategory": byCat,
	})
}

func (s *Server) handleAddCharge(w http.ResponseWriter, r *http.Request) {
	var c model.Treatment
	if err := decodeJSON(r, &c); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	p, err := s.db.AddCharge(pathID(r), c)
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	s.writeJSON(w, http.StatusCreated, p, fmt.Sprintf("收费已记录，累计总花费 %.2f 元", p.TotalCost))
}

func (s *Server) handleSummary(w http.ResponseWriter, r *http.Request) {
	p, err := s.db.Get(pathID(r))
	if err != nil {
		s.fail(w, statusOf(err), err)
		return
	}
	byCat := map[string]float64{}
	byDoctor := map[string]float64{}
	var maxCharge float64
	for _, c := range p.Charges {
		byCat[c.Category] += c.Amount
		byDoctor[c.Doctor] += c.Amount
		if c.Amount > maxCharge {
			maxCharge = c.Amount
		}
	}
	first, last := "", ""
	if len(p.Records) > 0 {
		dates := make([]string, 0, len(p.Records))
		for _, rec := range p.Records {
			dates = append(dates, rec.VisitDate)
		}
		sortStrings(dates)
		first, last = dates[0], dates[len(dates)-1]
	}
	avg := 0.0
	if len(p.Records) > 0 {
		avg = round2(p.TotalCost / float64(len(p.Records)))
	}
	s.ok(w, map[string]any{
		"id":              p.ID,
		"name":            p.Name,
		"species":         p.Species,
		"ownerName":       p.OwnerName,
		"ownerPhone":      p.OwnerPhone,
		"doctor":          p.Doctor,
		"disease":         p.Disease,
		"status":          p.Status,
		"totalCost":       p.TotalCost,
		"visitCount":      len(p.Records),
		"chargeCount":     len(p.Charges),
		"costByCategory":  byCat,
		"costByDoctor":    byDoctor,
		"maxSingleCharge": maxCharge,
		"avgCostPerVisit": avg,
		"firstVisit":      first,
		"lastVisit":       last,
		"historyText":     p.MedicalHistory(),
	})
}

// ---------------------------------------------------------------------------
// 批量 / 导出 / 管理
// ---------------------------------------------------------------------------

func (s *Server) handleBatchCreate(w http.ResponseWriter, r *http.Request) {
	var items []*model.Pet
	if err := decodeJSON(r, &items); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	if len(items) == 0 {
		s.fail(w, http.StatusBadRequest, errors.New("请求体需为非空数组"))
		return
	}
	created, errs := s.db.CreateMany(items)
	msgs := make([]string, 0, len(errs))
	for _, e := range errs {
		msgs = append(msgs, e.Error())
	}
	s.writeJSON(w, http.StatusCreated, map[string]any{
		"createdCount": len(created),
		"failedCount":  len(errs),
		"items":        created,
		"errors":       msgs,
	}, fmt.Sprintf("批量新增完成：成功 %d 条，失败 %d 条", len(created), len(errs)))
}

func (s *Server) handleBatchDelete(w http.ResponseWriter, r *http.Request) {
	var body struct {
		IDs []string `json:"ids"`
	}
	if err := decodeJSON(r, &body); err != nil {
		s.fail(w, http.StatusBadRequest, err)
		return
	}
	if len(body.IDs) == 0 {
		s.fail(w, http.StatusBadRequest, errors.New("ids 不能为空"))
		return
	}
	deleted, err := s.db.DeleteMany(body.IDs)
	if err != nil {
		s.fail(w, http.StatusInternalServerError, err)
		return
	}
	s.ok(w, map[string]any{
		"requested": len(body.IDs),
		"deleted":   len(deleted),
		"ids":       deleted,
		"missing":   len(body.IDs) - len(deleted),
	})
}

func (s *Server) handleExport(w http.ResponseWriter, r *http.Request) {
	format := strings.ToLower(r.URL.Query().Get("format"))
	all := s.db.All()
	switch format {
	case "csv":
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", `attachment; filename="pets.csv"`)
		cw := csv.NewWriter(w)
		_ = cw.Write([]string{"编号", "宠物姓名", "种类", "品种", "性别", "月龄", "主人姓名", "电话", "疾病", "医生姓名", "状态", "就诊次数", "总花费", "历史病历", "建档时间"})
		for _, p := range all {
			_ = cw.Write([]string{
				p.ID, p.Name, p.Species, p.Breed, p.Gender,
				strconv.Itoa(p.AgeMonths), p.OwnerName, p.OwnerPhone,
				p.Disease, p.Doctor, p.Status,
				strconv.Itoa(p.VisitCount), strconv.FormatFloat(p.TotalCost, 'f', 2, 64),
				p.MedicalHistory(), p.CreatedAt,
			})
		}
		cw.Flush()
	default:
		s.ok(w, map[string]any{
			"exportedAt": model.NowString(),
			"count":      len(all),
			"items":      all,
		})
	}
}

func (s *Server) handleCompact(w http.ResponseWriter, r *http.Request) {
	before := fileSize(s.db.Path())
	if err := s.db.Compact(); err != nil {
		s.fail(w, http.StatusInternalServerError, err)
		return
	}
	after := fileSize(s.db.Path())
	s.ok(w, map[string]any{
		"file":        s.db.Path(),
		"sizeBefore":  before,
		"sizeAfter":   after,
		"bytesFreed":  before - after,
		"recordCount": s.db.Count(),
	})
}

// SeedAll 返回「手工精选 + 批量生成」的完整模拟数据集。
// generated 为额外生成的随机档案数量（0 表示只用手工精选的 8 条）。
// 生成的档案使用固定随机种子，保证多次运行结果一致。
func SeedAll(generated int) []*model.Pet {
	base := SeedPets()
	if generated <= 0 {
		return base
	}
	gen := GeneratePets(generated, 20250101)
	// 生成数据不使用 PET-%06d 编号，避免与手工数据的自增主键冲突；
	// 但为稳妥起见仍显式指定独立前缀。
	all := make([]*model.Pet, 0, len(base)+len(gen))
	all = append(all, base...)
	all = append(all, gen...)
	return all
}

func (s *Server) handleSeed(w http.ResponseWriter, r *http.Request) {
	force := r.URL.Query().Get("force") == "true"
	if s.db.Count() > 0 && !force {
		s.fail(w, http.StatusConflict, fmt.Errorf("数据库已有 %d 条记录；如需强制写入演示数据请加 ?force=true", s.db.Count()))
		return
	}
	// ?count=N 额外生成 N 条随机档案；?count=all 生成默认 1000 条。
	generated := 0
	switch v := r.URL.Query().Get("count"); v {
	case "":
		generated = 0
	case "all":
		generated = 1000
	default:
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 || n > 50000 {
			s.fail(w, http.StatusBadRequest, fmt.Errorf("count 需为 0-50000 的整数或 all，收到 %q", v))
			return
		}
		generated = n
	}

	start := time.Now()
	created, errs := s.db.CreateManyCount(SeedAll(generated), 500)
	msgs := make([]string, 0, len(errs))
	for _, e := range errs {
		msgs = append(msgs, e.Error())
	}
	s.writeJSON(w, http.StatusCreated, map[string]any{
		"createdCount":   len(created),
		"generatedCount": generated,
		"failedCount":    len(errs),
		"totalInDB":      s.db.Count(),
		"elapsedMs":      time.Since(start).Milliseconds(),
		"dbSizeBytes":    fileSize(s.db.Path()),
		"errors":         msgs,
	}, fmt.Sprintf("模拟数据写入完成：新增 %d 条（其中随机生成 %d 条），耗时 %d ms", len(created), generated, time.Since(start).Milliseconds()))
}

// ---------------------------------------------------------------------------
// 兜底
// ---------------------------------------------------------------------------

func (s *Server) handleNotFound(w http.ResponseWriter, r *http.Request) {
	// 浏览器直接访问未知路径时，返回一个友好的 HTML 页面，而不是一堆 JSON。
	if isHTMLRequest(r) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(notFoundHTML(r.URL.Path)))
		return
	}
	s.writeJSON(w, http.StatusNotFound, map[string]any{
		"path":      r.URL.Path,
		"hint":      "接口不存在，访问 GET /api/v1/endpoints 查看全部接口",
		"endpoints": "/api/v1/endpoints",
	}, fmt.Sprintf("未找到路由 %s %s", r.Method, r.URL.Path))
}

// notFoundHTML 生成 404 页面（路径经 HTML 转义后再插入，避免 XSS）。
func notFoundHTML(path string) string {
	safe := html.EscapeString(path)
	return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">` +
		`<meta name="viewport" content="width=device-width,initial-scale=1">` +
		`<title>页面不存在 · 宠物医院</title><style>` +
		`body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;` +
		`background:#f6f7f9;color:#111827;font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}` +
		`.box{text-align:center;background:#fff;border:1px solid #e5e7eb;border-radius:14px;` +
		`padding:40px 48px;box-shadow:0 1px 3px rgba(0,0,0,.06)}` +
		`.c{font-size:52px;margin-bottom:8px}h1{font-size:19px;margin:0 0 6px}` +
		`p{color:#6b7280;margin:0 0 20px}code{background:#f3f4f6;padding:2px 7px;border-radius:5px;font-size:13px}` +
		`a{display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;padding:9px 18px;` +
		`border-radius:9px;font-weight:560}</style></head><body><div class="box">` +
		`<div class="c">🐾</div><h1>页面不存在</h1>` +
		`<p>找不到 <code>` + safe + `</code></p>` +
		`<a href="/">返回首页</a></div></body></html>`
}

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------

func fileSize(path string) int64 {
	if fi, err := statFile(path); err == nil {
		return fi
	}
	return 0
}

func round2(f float64) float64 { return float64(int64(f*100+0.5)) / 100 }

func sortStrings(s []string) {
	for i := 1; i < len(s); i++ {
		for j := i; j > 0 && s[j] < s[j-1]; j-- {
			s[j], s[j-1] = s[j-1], s[j]
		}
	}
}

// highlightAll 在检索结果中标注命中的关键词（便于人工核对）。
func highlightAll(items []*model.Pet, _ string) []*model.Pet { return items }
