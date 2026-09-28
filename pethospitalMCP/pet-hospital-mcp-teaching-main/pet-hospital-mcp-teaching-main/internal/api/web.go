package api

import (
	"embed"
	"io/fs"
	"net/http"
	"strings"
)

// webFS 把网页资源编译进可执行文件，保证单个二进制即可运行，
// 不需要额外携带 html/css/js 文件。
//
//go:embed web/index.html
var webFS embed.FS

// handleIndex 在根路径返回操作界面（网页）。
// 注意：JSON 版接口清单仍保留在 /api/v1/endpoints。
func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	// 只处理根路径；其他未匹配路径交给 handleNotFound。
	if r.URL.Path != "/" {
		s.handleNotFound(w, r)
		return
	}
	page, err := fs.ReadFile(webFS, "web/index.html")
	if err != nil {
		s.fail(w, http.StatusInternalServerError, err)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(page)
}

// registerWeb 注册网页相关路由。
func (s *Server) registerWeb() {
	s.mux.HandleFunc("GET /{$}", s.handleIndex)
	s.mux.HandleFunc("GET /favicon.ico", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/svg+xml")
		w.Header().Set("Cache-Control", "max-age=86400")
		_, _ = w.Write([]byte(faviconSVG))
	})
}

// faviconSVG 一个内联的爪印图标，避免额外的静态文件与 404。
const faviconSVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">` +
	`<text y="26" font-size="26">🐾</text></svg>`

// isHTMLRequest 判断请求是否来自浏览器（用于 404 时返回网页而非 JSON）。
func isHTMLRequest(r *http.Request) bool {
	return strings.Contains(r.Header.Get("Accept"), "text/html")
}
