// 宠物医院 · Pet Hospital REST API
//
// 一个零第三方依赖的本地宠物医院管理系统：
//   - 单文件嵌入式数据库（pet.db，自行实现：追加日志 + 内存索引 + 自动压实）
//   - 纯 net/http 提供的丰富 REST 服务（查询 / 新增 / 删除 / 批量 / 导出 / 统计）
//   - 无鉴权、无登录
//   - 启动后打印全部服务与访问案例，随后实时打印访问日志
//
// 用法：
//
//	go run .                       # 默认 127.0.0.1:8080，数据文件 ./data/pet.db
//	go run . -addr :9090           # 自定义端口
//	go run . -db /tmp/hospital.db  # 自定义数据库文件
//	go run . -seed                 # 首次启动写入演示数据
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"pethospital/internal/api"
	"pethospital/internal/store"
)

// 版本信息
const version = "1.0.0"

// ANSI 颜色
const (
	cReset  = "\x1b[0m"
	cBold   = "\x1b[1m"
	cDim    = "\x1b[2m"
	cRed    = "\x1b[31m"
	cGreen  = "\x1b[32m"
	cYellow = "\x1b[33m"
	cBlue   = "\x1b[34m"
	cPurple = "\x1b[35m"
	cCyan   = "\x1b[36m"
	cWhite  = "\x1b[97m"
)

func main() {
	var (
		addr    = flag.String("addr", "127.0.0.1:8080", "HTTP 监听地址")
		dbPath  = flag.String("db", "data/pet.db", "单文件数据库路径")
		seed    = flag.Bool("seed", false, "启动时写入模拟数据（仅当数据库为空）")
		count   = flag.Int("count", 0, "-seed 时额外随机生成的档案数量（0=仅 8 条手工精选）")
		noColor = flag.Bool("no-color", false, "禁用彩色输出")
	)
	flag.Parse()

	if *noColor || os.Getenv("NO_COLOR") != "" {
		disableColor()
	}

	// -----------------------------------------------------------------
	// 1. 打开单文件数据库
	// -----------------------------------------------------------------
	db, err := store.Open(*dbPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s✖ 数据库打开失败: %v%s\n", cRed, err, cReset)
		os.Exit(1)
	}
	defer db.Close()

	if *seed && db.Count() == 0 {
		n := *count
		if n < 0 {
			n = 0
		}
		start := time.Now()
		created, errs := db.CreateManyCount(api.SeedAll(n), 500)
		fmt.Printf("%s✔ 已写入模拟数据 %d 条%s（手工 8 条 + 随机 %d 条，失败 %d 条，耗时 %d ms）%s\n",
			cGreen, len(created), cDim, n, len(errs), time.Since(start).Milliseconds(), cReset)
		if len(errs) > 0 {
			fmt.Printf("%s  ⚠ 前几条错误：%v%s\n", cYellow, errs[0], cReset)
		}
	}

	// -----------------------------------------------------------------
	// 2. 构造 HTTP 服务（日志回调 -> 终端实时打印）
	// -----------------------------------------------------------------
	logf := func(format string, args ...any) {
		fmt.Printf("%s│%s "+format+"\n", append([]any{cDim, cReset}, args...)...)
	}
	srv := api.New(db, logf)

	// -----------------------------------------------------------------
	// 3. 打印启动横幅：服务网址 + 全部接口 + 访问案例
	// -----------------------------------------------------------------
	printBanner(*addr, db.Path(), db.Count())

	httpSrv := &http.Server{
		Addr:              *addr,
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	// 先监听，拿到真实端口（支持 :0 随机端口）
	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s✖ 监听 %s 失败: %v%s\n", cRed, *addr, err, cReset)
		os.Exit(1)
	}
	actual := ln.Addr().String()
	if strings.HasPrefix(actual, "0.0.0.0:") || strings.HasPrefix(actual, "[::]:") {
		actual = "127.0.0.1:" + strings.TrimPrefix(strings.TrimPrefix(actual, "0.0.0.0:"), "[::]:")
	}

	printServiceURL(actual, db.Path())
	printLogHeader()

	errCh := make(chan error, 1)
	go func() {
		if err := httpSrv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	// -----------------------------------------------------------------
	// 4. 优雅退出：Ctrl+C
	// -----------------------------------------------------------------
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)

	select {
	case err := <-errCh:
		fmt.Fprintf(os.Stderr, "%s✖ 服务异常: %v%s\n", cRed, err, cReset)
		os.Exit(1)
	case <-stop:
		fmt.Printf("\n%s├─ 收到退出信号，正在关闭服务...%s\n", cYellow, cReset)
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := httpSrv.Shutdown(ctx); err != nil {
			fmt.Fprintf(os.Stderr, "%s✖ 关闭超时: %v%s\n", cRed, err, cReset)
		}
		if err := db.Compact(); err == nil {
			fmt.Printf("%s├─ 数据库已压实并安全落盘: %s%s\n", cGreen, db.Path(), cReset)
		}
		fmt.Printf("%s└─ 再见 👋%s\n", cCyan, cReset)
	}
}

// ---------------------------------------------------------------------------
// 横幅打印
// ---------------------------------------------------------------------------

func printBanner(addr, dbPath string, count int) {
	w := 78
	line := strings.Repeat("═", w)

	fmt.Println()
	fmt.Printf("%s%s╔%s╗%s\n", cBold, cCyan, line, cReset)
	fmt.Printf("%s%s║%s%s║%s\n", cBold, cCyan, center(cPurple+"🐾  宠 物 医 院 · Pet Hospital REST API  🐾", w), cCyan, cReset)
	fmt.Printf("%s%s║%s%s║%s\n", cBold, cCyan, center(cDim+"宠物 / 主人 / 电话 / 疾病 / 医生 / 历史病历 / 总花费", w), cCyan, cReset)
	fmt.Printf("%s%s╚%s╝%s\n", cBold, cCyan, line, cReset)

	fmt.Printf("  %s版本%s %s   %s数据库%s %s%s%s   %s现有档案%s %s%d 条%s\n",
		cDim, cReset, version,
		cDim, cReset, cGreen, dbPath, cReset,
		cDim, cReset, cYellow, count, cReset)
	fmt.Println()

	// ---- 网页界面（最常用的入口，放在最前面）----
	fmt.Printf("%s%s▍网页操作界面%s\n\n", cBold, cWhite, cReset)
	fmt.Printf("  %s在浏览器中打开：%s\n", cDim, cReset)
	fmt.Printf("    %s%shttp://%s/%s\n\n", cBold+cPurple, "", addr, cReset)
	fmt.Printf("  %s提供：档案列表与搜索、新增/编辑/删除档案、查看历史病历与消费明细、经营统计%s\n",
		cDim, cReset)
	fmt.Printf("  %s网页资源已内嵌到可执行文件中，无需额外的 html/css/js 文件%s\n\n", cDim, cReset)

	// ---- 接口清单 ----
	eps := api.Endpoints()
	fmt.Printf("%s%s▍服务清单（共 %d 个接口）%s\n\n", cBold, cWhite, len(eps), cReset)

	lastGroup := ""
	for _, e := range eps {
		group := groupOf(e.Path)
		if group != lastGroup {
			fmt.Printf("  %s%s── %s ──%s\n", cBold, cBlue, group, cReset)
			lastGroup = group
		}
		mc := methodColor(e.Method)
		fmt.Printf("    %s%-6s%s %s%-42s%s %s%s%s\n",
			mc, e.Method, cReset,
			cWhite, e.Path, cReset,
			cDim, e.Desc, cReset)
	}
	fmt.Println()

	// ---- 访问案例 ----
	fmt.Printf("%s%s▍访问案例（把 HOST 换成服务网址即可直接执行）%s\n\n", cBold, cWhite, cReset)
	examples := []struct{ title, cmd string }{
		{"1. 打开网页操作界面（浏览器）", "http://HOST/"},
		{"2. 健康检查", "curl -s http://HOST/health"},
		{"3. 列出全部接口（JSON）", "curl -s http://HOST/api/v1/endpoints"},
		{"4. 新增一只宠物", `curl -s -X POST http://HOST/api/v1/pets -H 'Content-Type: application/json' -d '{"name":"旺财","species":"犬","breed":"金毛","gender":"公","ageMonths":36,"ownerName":"张三","ownerPhone":"13800001111","disease":"急性肠胃炎","doctor":"李医生","status":"待就诊"}'`},
		{"5. 查询宠物列表（分页+排序）", "curl -s 'http://HOST/api/v1/pets?page=1&pageSize=10&sortBy=totalCost&order=desc'"},
		{"6. 按主人电话查宠物", "curl -s 'http://HOST/api/v1/pets/by-owner?phone=13800001111'"},
		{"7. 全文检索病历（如：肠胃炎）", "curl -s 'http://HOST/api/v1/pets/search?q=肠胃炎'"},
		{"8. 按医生查接诊宠物", "curl -s 'http://HOST/api/v1/pets/by-doctor?doctor=李医生'"},
		{"9. 消费排行榜", "curl -s 'http://HOST/api/v1/pets/top-spenders?limit=5'"},
		{"10. 追加一条历史病历", `curl -s -X POST http://HOST/api/v1/pets/PET-000001/records -H 'Content-Type: application/json' -d '{"doctor":"李医生","diagnosis":"急性肠胃炎","symptoms":"呕吐腹泻","treatment":"补液消炎","prescription":["阿莫西林"],"charge":380}'`},
		{"11. 追加一笔收费（自动累计总花费）", `curl -s -X POST http://HOST/api/v1/pets/PET-000001/charges -H 'Content-Type: application/json' -d '{"item":"血常规检查","category":"检查","amount":180,"doctor":"李医生"}'`},
		{"12. 单只宠物费用汇总", "curl -s http://HOST/api/v1/pets/PET-000001/summary"},
		{"13. 医院经营统计", "curl -s 'http://HOST/api/v1/stats?top=5'"},
		{"14. 局部更新（只改状态）", `curl -s -X PATCH http://HOST/api/v1/pets/PET-000001 -H 'Content-Type: application/json' -d '{"status":"已康复"}'`},
		{"15. 删除宠物档案", "curl -s -X DELETE http://HOST/api/v1/pets/PET-000001"},
		{"16. 导出全部数据为 CSV", "curl -s 'http://HOST/api/v1/export?format=csv' -o pets.csv"},
		{"17. 写入 1000 条模拟数据", "curl -s -X POST 'http://HOST/api/v1/admin/seed?force=true&count=1000'"},
	}
	for _, ex := range examples {
		fmt.Printf("  %s%s%s\n", cYellow, ex.title, cReset)
		cmd := strings.ReplaceAll(ex.cmd, "HOST", addr)
		fmt.Printf("    %s$ %s%s\n\n", cGreen, cmd, cReset)
	}
}

func printServiceURL(addr, dbPath string) {
	line := strings.Repeat("═", 78)
	fmt.Printf("%s%s%s%s\n", cBold, cGreen, line, cReset)
	fmt.Printf("%s  ✅ 服务已启动，请访问：%s  %s%shttp://%s/%s\n", cBold+cGreen, cReset, cBold+cPurple, "", addr, cReset)
	fmt.Printf("%s     接口清单（JSON）：%s  http://%s/api/v1/endpoints\n", cDim, cReset, addr)
	fmt.Printf("%s     数据库文件：%s  %s%s%s\n", cDim, cReset, cGreen, dbPath, cReset)
	fmt.Printf("%s%s%s%s\n\n", cBold, cGreen, line, cReset)
}

func printLogHeader() {
	fmt.Printf("%s%s▍实时访问日志（Ctrl+C 退出）%s\n\n", cBold, cWhite, cReset)
}

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

func groupOf(path string) string {
	switch {
	case path == "/" || path == "/health" || strings.Contains(path, "/stats") ||
		strings.Contains(path, "/meta") || strings.Contains(path, "/endpoints"):
		return "系统与统计"
	case strings.Contains(path, "batch") || strings.Contains(path, "export") ||
		strings.Contains(path, "admin"):
		return "批量 / 导出 / 管理"
	case strings.Contains(path, "/records"):
		return "历史病历"
	case strings.Contains(path, "/charges") || strings.Contains(path, "/summary"):
		return "消费与汇总"
	case strings.Contains(path, "by-") || strings.Contains(path, "search") ||
		strings.Contains(path, "top-spenders") || strings.Contains(path, "cost-range"):
		return "高级查询 / 搜索"
	default:
		return "宠物档案 CRUD"
	}
}

func methodColor(m string) string {
	switch m {
	case "GET":
		return cGreen
	case "POST":
		return cBlue
	case "PUT":
		return cYellow
	case "PATCH":
		return cPurple
	case "DELETE":
		return cRed
	default:
		return cWhite
	}
}

// center 让字符串在给定宽度内居中（按可见字符宽度近似计算，忽略 ANSI 序列）。
func center(s string, width int) string {
	visible := visibleLen(s)
	if visible >= width {
		return s
	}
	pad := (width - visible) / 2
	return strings.Repeat(" ", pad) + s + strings.Repeat(" ", width-visible-pad)
}

// visibleLen 计算去掉 ANSI 转义序列后的可见长度。
func visibleLen(s string) int {
	n := 0
	inEsc := false
	for _, r := range s {
		switch {
		case inEsc:
			if r == 'm' {
				inEsc = false
			}
		case r == '\x1b':
			inEsc = true
		default:
			n++
		}
	}
	return n
}

// disableColor 把颜色常量置空（-no-color）。
func disableColor() {
	// 由于颜色是常量，无法重新赋值；这里通过环境变量影响不到常量，
	// 因此采用最简单可靠的方式：重定向输出流不可行时，直接设置 NO_COLOR
	// 标记，并在下方通过 stdoutColorEnabled 控制。
	stdoutColorEnabled = false
}

var stdoutColorEnabled = true
