// Package store 实现一个「本地单文件」嵌入式数据库。
//
// 设计（零第三方依赖，纯 Go 标准库）：
//
//	pet.db 文件布局：
//	┌──────────────────────────────────────────────────────────────┐
//	│ Header (32 字节)                                             │
//	│   magic  "PETDBv1\n" (8B)                                    │
//	│   version uint32 (4B)   = 1                                  │
//	│   flags   uint32 (4B)   = 0(活跃) / 1(压实中)                │
//	│   reserved         (16B)                                     │
//	├──────────────────────────────────────────────────────────────┤
//	│ Record 记录区（顺序追加，永不原地修改）                       │
//	│   [len uint32][crc32 uint32][json payload ...]               │
//	│   payload: {"op":"put|del","id":"...","data":{...Pet}}        │
//	└──────────────────────────────────────────────────────────────┘
//
// 读路径：启动时顺序回放日志，构建内存 map 索引（id -> Pet）。
// 写路径：向文件追加一条记录 + fsync，并同步更新内存索引。
// 压实：日志中删除/更新产生的垃圾超过阈值时，原子重写文件
//
//	（写 pet.db.tmp -> fsync -> rename），保证崩溃安全。
//
// 并发：单个 sync.RWMutex 保护内存索引；写操作持有写锁，
//
//	因此写入天然串行，日志追加不会交错。
package store

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"pethospital/internal/model"
)

// ---------------------------------------------------------------------------
// 常量与错误
// ---------------------------------------------------------------------------

const (
	magic      = "PETDBv1\n"
	headerSize = 32
	// 日志垃圾比例超过该值时自动压实。
	compactThreshold = 4.0
	// 至少要有这么多条冗余记录才值得压实。
	compactMinGarbage = 64
)

// ErrNotFound 记录不存在。
var ErrNotFound = errors.New("记录不存在")

// ErrDuplicate 主键冲突。
var ErrDuplicate = errors.New("记录已存在")

// op 日志操作类型。
type op string

const (
	opPut op = "put"
	opDel op = "del"
)

// logRecord 一条日志记录的 payload。
type logRecord struct {
	Op   op         `json:"op"`
	ID   string     `json:"id"`
	Data *model.Pet `json:"data,omitempty"`
}

// ---------------------------------------------------------------------------
// 查询选项
// ---------------------------------------------------------------------------

// Query 列表查询参数。
type Query struct {
	Search     string  // 全文模糊匹配（跨字段）
	Name       string  // 宠物姓名模糊
	OwnerName  string  // 主人姓名模糊
	OwnerPhone string  // 电话模糊
	Species    string  // 种类精确
	Doctor     string  // 医生模糊
	Disease    string  // 疾病模糊
	Status     string  // 状态精确
	MinCost    float64 // 最低总花费
	MaxCost    float64 // 最高总花费
	HasCost    bool    // 是否启用花费区间过滤
	SortBy     string  // id/name/ownerName/species/doctor/totalCost/visitCount/createdAt/updatedAt
	Order      string  // asc/desc
	Page       int     // 页码，从 1 开始
	PageSize   int     // 每页条数
}

// Result 列表查询结果。
type Result struct {
	Items      []*model.Pet `json:"items"`
	Total      int          `json:"total"`      // 过滤后总数
	Page       int          `json:"page"`       // 当前页
	PageSize   int          `json:"pageSize"`   // 每页条数
	TotalPages int          `json:"totalPages"` // 总页数
	TotalCost  float64      `json:"totalCost"`  // 结果集花费合计
}

// Stats 统计信息。
type Stats struct {
	TotalPets       int                `json:"totalPets"`
	TotalRecords    int                `json:"totalRecords"`
	TotalCharges    int                `json:"totalCharges"`
	TotalRevenue    float64            `json:"totalRevenue"`
	AverageCost     float64            `json:"averageCost"`
	MaxCost         float64            `json:"maxCost"`
	BySpecies       map[string]int     `json:"bySpecies"`
	ByStatus        map[string]int     `json:"byStatus"`
	ByDoctor        map[string]int     `json:"byDoctor"`
	RevenueByDoctor map[string]float64 `json:"revenueByDoctor"`
	TopSpenders     []*model.Pet       `json:"topSpenders"`
	LogGarbagePct   float64            `json:"logGarbagePct"`
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

// Store 单文件嵌入式数据库。
type Store struct {
	mu     sync.RWMutex
	path   string
	file   *os.File
	data   map[string]*model.Pet // 内存索引
	alive  int                   // 当前有效记录数
	total  int                   // 日志中的记录总数（含垃圾）
	offset int64                 // 当前日志写入位置（字节），避免每次写入都 Seek 到文件尾
	closed bool
}

// Open 打开（或创建）数据库文件。若文件损坏，会尽量回放到最后一个
// 完整记录并截断损坏部分，而不是直接失败。
func Open(path string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("创建数据目录失败: %w", err)
	}
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return nil, fmt.Errorf("打开数据库失败: %w", err)
	}
	s := &Store{path: path, file: f, data: make(map[string]*model.Pet)}

	info, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, err
	}

	if info.Size() == 0 {
		if err := s.writeHeader(); err != nil {
			f.Close()
			return nil, err
		}
		return s, nil
	}

	if err := s.readHeader(); err != nil {
		f.Close()
		return nil, err
	}
	if err := s.replay(info.Size()); err != nil {
		f.Close()
		return nil, err
	}
	if s.shouldCompact() {
		if err := s.compactLocked(); err != nil {
			return nil, err
		}
	}
	return s, nil
}

// Path 返回数据库文件路径。
func (s *Store) Path() string { return s.path }

// Close 关闭数据库。
func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	if s.file == nil {
		return nil
	}
	return s.file.Close()
}

// ---------------------------------------------------------------------------
// 头部
// ---------------------------------------------------------------------------

func (s *Store) writeHeader() error {
	var h [headerSize]byte
	copy(h[0:8], magic)
	binary.LittleEndian.PutUint32(h[8:12], 1)  // version
	binary.LittleEndian.PutUint32(h[12:16], 0) // flags
	if _, err := s.file.WriteAt(h[:], 0); err != nil {
		return err
	}
	return s.file.Sync()
}

func (s *Store) readHeader() error {
	var h [headerSize]byte
	if _, err := io.ReadFull(io.NewSectionReader(s.file, 0, headerSize), h[:]); err != nil {
		return fmt.Errorf("读取数据库头部失败: %w", err)
	}
	if string(h[0:8]) != magic {
		return fmt.Errorf("不是有效的 pet.db 文件（magic 不匹配）: %s", s.path)
	}
	if v := binary.LittleEndian.Uint32(h[8:12]); v != 1 {
		return fmt.Errorf("不支持的数据库版本: %d", v)
	}
	return nil
}

// ---------------------------------------------------------------------------
// 日志回放 / 追加
// ---------------------------------------------------------------------------

// replay 顺序回放日志，重建内存索引。
// 遇到损坏的尾部记录（比如断电导致写到一半）时截断到最后一个
// 完整记录并继续，保证数据库可用。
func (s *Store) replay(size int64) error {
	r := io.NewSectionReader(s.file, headerSize, size-headerSize)
	var offset int64 = headerSize
	hdr := make([]byte, 8)

	for {
		if _, err := io.ReadFull(r, hdr); err != nil {
			if err == io.EOF {
				break
			}
			// 尾部不完整：截断。
			if err == io.ErrUnexpectedEOF {
				return s.truncateTo(offset)
			}
			return err
		}
		length := binary.LittleEndian.Uint32(hdr[0:4])
		sum := binary.LittleEndian.Uint32(hdr[4:8])
		if length == 0 || length > 64<<20 { // 64MB 单条上限，防脏数据
			return s.truncateTo(offset)
		}
		payload := make([]byte, length)
		if _, err := io.ReadFull(r, payload); err != nil {
			return s.truncateTo(offset)
		}
		if crc32.ChecksumIEEE(payload) != sum {
			return s.truncateTo(offset)
		}
		var rec logRecord
		if err := json.Unmarshal(payload, &rec); err != nil {
			return s.truncateTo(offset)
		}
		s.apply(&rec)
		s.total++
		offset += int64(8 + length)
	}

	// 回放完成，定位到文件末尾准备追加。
	s.offset = offset
	return nil
}

func (s *Store) truncateTo(offset int64) error {
	if err := s.file.Truncate(offset); err != nil {
		return err
	}
	s.offset = offset
	return s.file.Sync()
}

func (s *Store) apply(rec *logRecord) {
	switch rec.Op {
	case opPut:
		if rec.Data != nil {
			if _, exists := s.data[rec.ID]; !exists {
				s.alive++
			}
			s.data[rec.ID] = rec.Data
		}
	case opDel:
		if _, exists := s.data[rec.ID]; exists {
			delete(s.data, rec.ID)
			s.alive--
		}
	}
}

// appendLocked 追加一条记录。调用方必须持有写锁。
func (s *Store) appendLocked(rec *logRecord) error {
	if s.closed {
		return errors.New("数据库已关闭")
	}
	payload, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	buf := make([]byte, 8+len(payload))
	binary.LittleEndian.PutUint32(buf[0:4], uint32(len(payload)))
	binary.LittleEndian.PutUint32(buf[4:8], crc32.ChecksumIEEE(payload))
	copy(buf[8:], payload)

	if _, err := s.file.WriteAt(buf, s.offset); err != nil {
		return err
	}
	s.offset += int64(len(buf))
	if err := s.file.Sync(); err != nil { // fsync：保证落盘
		return err
	}
	s.apply(rec)
	s.total++
	return nil
}

// ---------------------------------------------------------------------------
// 压实
// ---------------------------------------------------------------------------

func (s *Store) shouldCompact() bool {
	garbage := s.total - s.alive
	return garbage >= compactMinGarbage &&
		float64(s.total) > float64(s.alive)*compactThreshold
}

// compactLocked 原子重写数据库文件，只保留有效记录。调用方须持有写锁。
func (s *Store) compactLocked() error {
	if s.closed {
		return errors.New("数据库已关闭")
	}
	tmp := s.path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_RDWR|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return fmt.Errorf("压实失败(创建临时文件): %w", err)
	}
	defer func() {
		f.Close()
		os.Remove(tmp) // 成功时 rename 后此处为 no-op
	}()

	// 写头部
	var h [headerSize]byte
	copy(h[0:8], magic)
	binary.LittleEndian.PutUint32(h[8:12], 1)
	written, err := f.Write(h[:])
	if err != nil {
		return err
	}
	// 记录新文件的有效长度，供压实后重置写入偏移使用。
	newSize := int64(written)

	// 按 id 排序后写出，保证文件内容确定、可 diff。
	ids := make([]string, 0, len(s.data))
	for id := range s.data {
		ids = append(ids, id)
	}
	sort.Strings(ids)

	for _, id := range ids {
		rec := &logRecord{Op: opPut, ID: id, Data: s.data[id]}
		payload, err := json.Marshal(rec)
		if err != nil {
			return err
		}
		buf := make([]byte, 8+len(payload))
		binary.LittleEndian.PutUint32(buf[0:4], uint32(len(payload)))
		binary.LittleEndian.PutUint32(buf[4:8], crc32.ChecksumIEEE(payload))
		copy(buf[8:], payload)
		if n, err := f.Write(buf); err != nil {
			return err
		} else {
			newSize += int64(n)
		}
	}
	if err := f.Sync(); err != nil {
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	// Windows 不允许 rename 覆盖仍被本进程打开的文件，必须先关闭旧句柄。
	if err := s.file.Close(); err != nil {
		return fmt.Errorf("压实失败(关闭旧文件): %w", err)
	}
	if err := os.Rename(tmp, s.path); err != nil {
		// 替换失败时原文件仍在，尽力恢复句柄让 Store 可继续使用。
		nf, reopenErr := os.OpenFile(s.path, os.O_RDWR, 0o644)
		if reopenErr == nil {
			s.file = nf
			return fmt.Errorf("压实失败(替换文件): %w", err)
		}
		s.file = nil
		s.closed = true
		return fmt.Errorf("压实失败(替换文件): %w；重新打开原数据库失败: %v", err, reopenErr)
	}
	// 重新打开文件句柄
	nf, err := os.OpenFile(s.path, os.O_RDWR, 0o644)
	if err != nil {
		s.file = nil
		s.closed = true
		return fmt.Errorf("压实已替换数据库但重新打开失败: %w", err)
	}
	s.file = nf
	s.offset = newSize
	s.total = s.alive
	return nil
}

// Compact 手动触发压实。
func (s *Store) Compact() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.compactLocked()
}

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------

// Create 新增宠物。id 为空时自动生成。
func (s *Store) Create(p *model.Pet) (*model.Pet, error) {
	if err := p.Validate(); err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	if p.ID == "" {
		p.ID = s.nextIDLocked()
	}
	if _, exists := s.data[p.ID]; exists {
		return nil, fmt.Errorf("%w: id=%s", ErrDuplicate, p.ID)
	}
	now := model.NowString()
	p.CreatedAt = now
	p.Recalc()
	s.normalize(p)

	if err := s.appendLocked(&logRecord{Op: opPut, ID: p.ID, Data: p}); err != nil {
		return nil, err
	}
	return clone(p), nil
}

// Get 按 id 查询。
func (s *Store) Get(id string) (*model.Pet, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.data[id]
	if !ok {
		return nil, fmt.Errorf("%w: id=%s", ErrNotFound, id)
	}
	return clone(p), nil
}

// Update 全量更新（PUT）。
func (s *Store) Update(id string, in *model.Pet) (*model.Pet, error) {
	if err := in.Validate(); err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	old, ok := s.data[id]
	if !ok {
		return nil, fmt.Errorf("%w: id=%s", ErrNotFound, id)
	}
	in.ID = id
	in.CreatedAt = old.CreatedAt // 创建时间不可篡改
	in.Recalc()
	s.normalize(in)
	if err := s.appendLocked(&logRecord{Op: opPut, ID: id, Data: in}); err != nil {
		return nil, err
	}
	return clone(in), nil
}

// Patch 局部更新（PATCH）：只覆盖传入的非 nil 字段。
func (s *Store) Patch(id string, patch *model.Pet, fields map[string]bool) (*model.Pet, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.data[id]
	if !ok {
		return nil, fmt.Errorf("%w: id=%s", ErrNotFound, id)
	}
	next := clone(p)
	applyPatch(next, patch, fields)
	if err := next.Validate(); err != nil {
		return nil, err
	}
	next.Recalc()
	s.normalize(next)
	if err := s.appendLocked(&logRecord{Op: opPut, ID: id, Data: next}); err != nil {
		return nil, err
	}
	return clone(next), nil
}

// Delete 删除。
func (s *Store) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.data[id]; !ok {
		return fmt.Errorf("%w: id=%s", ErrNotFound, id)
	}
	if err := s.appendLocked(&logRecord{Op: opDel, ID: id}); err != nil {
		return err
	}
	if s.shouldCompact() {
		return s.compactLocked()
	}
	return nil
}

// DeleteMany 批量删除，返回实际删除的 id。
func (s *Store) DeleteMany(ids []string) ([]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var deleted []string
	for _, id := range ids {
		if _, ok := s.data[id]; !ok {
			continue
		}
		if err := s.appendLocked(&logRecord{Op: opDel, ID: id}); err != nil {
			return deleted, err
		}
		deleted = append(deleted, id)
	}
	if s.shouldCompact() {
		if err := s.compactLocked(); err != nil {
			return deleted, err
		}
	}
	return deleted, nil
}

// CreateMany 批量新增（单事务语义：逐条追加）。
// 与 Create 不同，这里只在最后 fsync 一次，适合大批量灌数据。
func (s *Store) CreateMany(items []*model.Pet) ([]*model.Pet, []error) {
	return s.CreateManyCount(items, 0)
}

// CreateManyCount 批量新增，并返回实际写入的记录数。
// 每累计 fsyncEvery 条记录同步一次磁盘；fsyncEvery <= 0 时使用默认值 200。
// 返回的 count 为本次成功追加到日志的记录条数（用于统计写入指标）。
func (s *Store) CreateManyCount(items []*model.Pet, fsyncEvery int) (created []*model.Pet, errs []error) {
	if fsyncEvery <= 0 {
		fsyncEvery = 200
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	out := make([]*model.Pet, 0, len(items))
	errList := make([]error, 0)
	pending := 0

	for _, p := range items {
		if err := p.Validate(); err != nil {
			errList = append(errList, err)
			continue
		}
		if p.ID == "" {
			p.ID = s.nextIDLocked()
		}
		if _, exists := s.data[p.ID]; exists {
			errList = append(errList, fmt.Errorf("%w: id=%s", ErrDuplicate, p.ID))
			continue
		}
		now := model.NowString()
		p.CreatedAt = now
		p.Recalc()
		s.normalize(p)

		// 原子写入内存索引，保证 nextIDLocked 能立刻看到新记录。
		s.apply(&logRecord{Op: opPut, ID: p.ID, Data: p})
		s.total++
		if err := s.appendNoSync(&logRecord{Op: opPut, ID: p.ID, Data: p}); err != nil {
			// 回滚内存索引，避免与日志不一致。
			delete(s.data, p.ID)
			s.alive--
			s.total--
			errList = append(errList, err)
			continue
		}
		out = append(out, clone(p))
		pending++
		if pending >= fsyncEvery {
			if err := s.file.Sync(); err != nil {
				errList = append(errList, err)
			}
			pending = 0
		}
	}
	if pending > 0 {
		if err := s.file.Sync(); err != nil {
			errList = append(errList, err)
		}
	}
	return out, errList
}

// appendNoSync 追加一条记录但不 fsync（由调用方统一同步）。
// 调用方必须持有写锁。
func (s *Store) appendNoSync(rec *logRecord) error {
	if s.closed {
		return errors.New("数据库已关闭")
	}
	payload, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	buf := make([]byte, 8+len(payload))
	binary.LittleEndian.PutUint32(buf[0:4], uint32(len(payload)))
	binary.LittleEndian.PutUint32(buf[4:8], crc32.ChecksumIEEE(payload))
	copy(buf[8:], payload)

	if _, err := s.file.WriteAt(buf, s.offset); err != nil {
		return err
	}
	s.offset += int64(len(buf))
	return nil
}

// ---------------------------------------------------------------------------
// 病历与收费子资源
// ---------------------------------------------------------------------------

// AddRecord 追加一条病历。
func (s *Store) AddRecord(id string, rec model.MedicalRecord) (*model.Pet, error) {
	if strings.TrimSpace(rec.Diagnosis) == "" {
		return nil, errors.New("diagnosis(诊断结论) 不能为空")
	}
	if strings.TrimSpace(rec.Doctor) == "" {
		return nil, errors.New("doctor(医生姓名) 不能为空")
	}
	if rec.Charge < 0 {
		return nil, errors.New("charge(本次费用) 不能为负数")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.data[id]
	if !ok {
		return nil, fmt.Errorf("%w: id=%s", ErrNotFound, id)
	}
	next := clone(p)
	if rec.ID == "" {
		rec.ID = fmt.Sprintf("MR-%d", time.Now().UnixNano())
	}
	if rec.VisitDate == "" {
		rec.VisitDate = time.Now().Format("2006-01-02")
	}
	rec.CreatedAt = model.NowString()
	next.Records = append(next.Records, rec)
	if rec.Doctor != "" {
		next.Doctor = rec.Doctor // 主治医生跟随最近一次就诊
	}
	next.Recalc()
	if err := s.appendLocked(&logRecord{Op: opPut, ID: id, Data: next}); err != nil {
		return nil, err
	}
	return clone(next), nil
}

// AddCharge 追加一条收费明细。
func (s *Store) AddCharge(id string, c model.Treatment) (*model.Pet, error) {
	if strings.TrimSpace(c.Item) == "" {
		return nil, errors.New("item(收费项目) 不能为空")
	}
	if c.Amount < 0 {
		return nil, errors.New("amount(金额) 不能为负数")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.data[id]
	if !ok {
		return nil, fmt.Errorf("%w: id=%s", ErrNotFound, id)
	}
	next := clone(p)
	if c.ID == "" {
		c.ID = fmt.Sprintf("CH-%d", time.Now().UnixNano())
	}
	if c.Date == "" {
		c.Date = time.Now().Format("2006-01-02")
	}
	next.Charges = append(next.Charges, c)
	next.Recalc()
	if err := s.appendLocked(&logRecord{Op: opPut, ID: id, Data: next}); err != nil {
		return nil, err
	}
	return clone(next), nil
}

// ---------------------------------------------------------------------------
// 查询
// ---------------------------------------------------------------------------

// List 条件查询 + 排序 + 分页。
func (s *Store) List(q Query) Result {
	s.mu.RLock()
	defer s.mu.RUnlock()

	matched := make([]*model.Pet, 0, len(s.data))
	var sum float64
	for _, p := range s.data {
		if !match(p, &q) {
			continue
		}
		cp := clone(p)
		matched = append(matched, cp)
		sum += cp.TotalCost
	}

	sortPets(matched, q.SortBy, q.Order)

	page, size := q.Page, q.PageSize
	if page < 1 {
		page = 1
	}
	if size < 1 {
		size = 20
	}
	if size > 500 {
		size = 500
	}
	total := len(matched)
	totalPages := (total + size - 1) / size
	start := (page - 1) * size
	end := start + size
	if start > total {
		start = total
	}
	if end > total {
		end = total
	}
	items := matched[start:end]
	if items == nil {
		items = []*model.Pet{}
	}
	return Result{
		Items:      items,
		Total:      total,
		Page:       page,
		PageSize:   size,
		TotalPages: totalPages,
		TotalCost:  sum,
	}
}

// All 返回全部记录（用于导出）。
func (s *Store) All() []*model.Pet {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]*model.Pet, 0, len(s.data))
	for _, p := range s.data {
		out = append(out, clone(p))
	}
	sortPets(out, "createdAt", "desc")
	return out
}

// Count 当前记录数。
func (s *Store) Count() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.data)
}

// Stats 汇总统计。
func (s *Store) Stats(topN int) Stats {
	s.mu.RLock()
	defer s.mu.RUnlock()

	st := Stats{
		BySpecies:       map[string]int{},
		ByStatus:        map[string]int{},
		ByDoctor:        map[string]int{},
		RevenueByDoctor: map[string]float64{},
	}
	all := make([]*model.Pet, 0, len(s.data))
	for _, p := range s.data {
		all = append(all, clone(p))
	}
	for _, p := range all {
		st.TotalPets++
		st.TotalRecords += len(p.Records)
		st.TotalCharges += len(p.Charges)
		st.TotalRevenue += p.TotalCost
		st.BySpecies[p.Species]++
		st.ByStatus[p.Status]++
		st.ByDoctor[p.Doctor]++
		st.RevenueByDoctor[p.Doctor] += p.TotalCost
		if p.TotalCost > st.MaxCost {
			st.MaxCost = p.TotalCost
		}
	}
	if st.TotalPets > 0 {
		st.AverageCost = round2(st.TotalRevenue / float64(st.TotalPets))
	}
	st.TotalRevenue = round2(st.TotalRevenue)
	st.MaxCost = round2(st.MaxCost)

	sort.Slice(all, func(i, j int) bool { return all[i].TotalCost > all[j].TotalCost })
	if topN <= 0 {
		topN = 5
	}
	if len(all) > topN {
		all = all[:topN]
	}
	st.TopSpenders = all

	if s.total > 0 {
		st.LogGarbagePct = round2(float64(s.total-s.alive) / float64(s.total) * 100)
	}
	return st
}

// ---------------------------------------------------------------------------
// 匹配 / 排序 / 工具
// ---------------------------------------------------------------------------

func match(p *model.Pet, q *Query) bool {
	if q.Species != "" && p.Species != q.Species {
		return false
	}
	if q.Status != "" && p.Status != q.Status {
		return false
	}
	if q.HasCost && (p.TotalCost < q.MinCost || p.TotalCost > q.MaxCost) {
		return false
	}
	// 子串匹配统一大小写不敏感
	if !containsFold(p.Name, q.Name) {
		return false
	}
	if !containsFold(p.OwnerName, q.OwnerName) {
		return false
	}
	if !containsFold(p.OwnerPhone, q.OwnerPhone) {
		return false
	}
	if !containsFold(p.Doctor, q.Doctor) {
		return false
	}
	if !containsFold(p.Disease, q.Disease) {
		return false
	}
	if q.Search != "" && !matchesSearch(p, q.Search) {
		return false
	}
	return true
}

// matchesSearch 全文检索：按空白拆词，所有词都要命中（AND），
// 命中范围覆盖主档字段 + 病历全文 + 收费项目。
func matchesSearch(p *model.Pet, search string) bool {
	haystack := strings.ToLower(strings.Join([]string{
		p.ID, p.Name, p.Species, p.Breed, p.Gender, p.Color, p.ChipNo,
		p.OwnerName, p.OwnerPhone, p.OwnerAddr,
		p.Doctor, p.Disease, p.Status, p.Allergy, p.Note,
		p.MedicalHistory(),
	}, " "))
	// 附带收费项目
	for _, c := range p.Charges {
		haystack += " " + strings.ToLower(c.Item+" "+c.Category+" "+c.Doctor+" "+c.Note)
	}
	for _, w := range strings.Fields(strings.ToLower(search)) {
		if !strings.Contains(haystack, w) {
			return false
		}
	}
	return true
}

func containsFold(hay, needle string) bool {
	if needle == "" {
		return true
	}
	return strings.Contains(strings.ToLower(hay), strings.ToLower(needle))
}

func sortPets(list []*model.Pet, by, order string) {
	if by == "" {
		by = "createdAt"
	}
	desc := strings.EqualFold(order, "desc")
	if order == "" {
		desc = true
	}
	less := func(a, b *model.Pet) bool {
		switch by {
		case "name":
			return a.Name < b.Name
		case "ownerName":
			return a.OwnerName < b.OwnerName
		case "species":
			return a.Species < b.Species
		case "doctor":
			return a.Doctor < b.Doctor
		case "disease":
			return a.Disease < b.Disease
		case "status":
			return a.Status < b.Status
		case "totalCost":
			return a.TotalCost < b.TotalCost
		case "visitCount":
			return a.VisitCount < b.VisitCount
		case "updatedAt":
			return a.UpdatedAt < b.UpdatedAt
		case "createdAt":
			return a.CreatedAt < b.CreatedAt
		default: // id
			return a.ID < b.ID
		}
	}
	sort.SliceStable(list, func(i, j int) bool {
		if less(list[i], list[j]) {
			return !desc
		}
		if less(list[j], list[i]) {
			return desc
		}
		return false
	})
}

// normalize 统一填充默认值与补齐子项 id。
func (s *Store) normalize(p *model.Pet) {
	if p.Species == "" {
		p.Species = model.SpeciesOther
	}
	if p.Status == "" {
		p.Status = model.StatusWaiting
	}
	for i := range p.Records {
		if p.Records[i].ID == "" {
			p.Records[i].ID = fmt.Sprintf("MR-%d-%d", time.Now().UnixNano(), i)
		}
		if p.Records[i].VisitDate == "" {
			p.Records[i].VisitDate = time.Now().Format("2006-01-02")
		}
		if p.Records[i].CreatedAt == "" {
			p.Records[i].CreatedAt = model.NowString()
		}
	}
	for i := range p.Charges {
		if p.Charges[i].ID == "" {
			p.Charges[i].ID = fmt.Sprintf("CH-%d-%d", time.Now().UnixNano(), i)
		}
		if p.Charges[i].Date == "" {
			p.Charges[i].Date = time.Now().Format("2006-01-02")
		}
	}
}

// nextIDLocked 生成递增 id：PET-000001。
func (s *Store) nextIDLocked() string {
	max := 0
	for id := range s.data {
		var n int
		if _, err := fmt.Sscanf(id, "PET-%d", &n); err == nil && n > max {
			max = n
		}
	}
	return fmt.Sprintf("PET-%06d", max+1)
}

// applyPatch 把 patch 中出现的字段拷贝到 dst。
func applyPatch(dst, patch *model.Pet, fields map[string]bool) {
	set := func(name string) bool {
		if fields == nil {
			return false
		}
		return fields[name]
	}
	if set("name") {
		dst.Name = patch.Name
	}
	if set("species") {
		dst.Species = patch.Species
	}
	if set("breed") {
		dst.Breed = patch.Breed
	}
	if set("gender") {
		dst.Gender = patch.Gender
	}
	if set("ageMonths") {
		dst.AgeMonths = patch.AgeMonths
	}
	if set("color") {
		dst.Color = patch.Color
	}
	if set("chipNo") {
		dst.ChipNo = patch.ChipNo
	}
	if set("ownerName") {
		dst.OwnerName = patch.OwnerName
	}
	if set("ownerPhone") {
		dst.OwnerPhone = patch.OwnerPhone
	}
	if set("ownerAddr") {
		dst.OwnerAddr = patch.OwnerAddr
	}
	if set("doctor") {
		dst.Doctor = patch.Doctor
	}
	if set("disease") {
		dst.Disease = patch.Disease
	}
	if set("status") {
		dst.Status = patch.Status
	}
	if set("allergy") {
		dst.Allergy = patch.Allergy
	}
	if set("note") {
		dst.Note = patch.Note
	}
	if set("records") {
		dst.Records = patch.Records
	}
	if set("charges") {
		dst.Charges = patch.Charges
	}
}

// clone 深拷贝，避免调用方改到内存索引里的对象。
func clone(p *model.Pet) *model.Pet {
	if p == nil {
		return nil
	}
	b, err := json.Marshal(p)
	if err != nil {
		return nil
	}
	var out model.Pet
	if err := json.Unmarshal(b, &out); err != nil {
		return nil
	}
	return &out
}

func round2(f float64) float64 {
	return float64(int64(f*100+0.5)) / 100
}
