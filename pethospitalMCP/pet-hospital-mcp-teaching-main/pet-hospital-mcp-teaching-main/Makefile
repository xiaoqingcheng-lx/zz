# 宠物医院系统 · 构建与发行
#
#   make help      查看全部命令
#   make dist      构建发行包（可执行文件 + 测试数据库 + 说明文档）
#   make build     仅编译可执行文件到 dist/

BIN      := pethospital
DIST     := dist
PKG      := .
SEED     := 1000
GOOS     ?= $(shell go env GOOS)
GOARCH   ?= $(shell go env GOARCH)
HOST_GOOS := $(shell go env GOHOSTOS)
HOST_GOARCH := $(shell go env GOHOSTARCH)
EXT      := $(if $(filter windows,$(GOOS)),.exe,)
LDFLAGS  := -s -w

.DEFAULT_GOAL := help
.PHONY: help build dist test-db run seed vet fmt tidy clean cross

help: ## 显示本帮助
	@echo "宠物医院系统 · 可用命令："
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo

build: ## 编译可执行文件到 dist/pethospital
	@mkdir -p $(DIST)
	CGO_ENABLED=0 GOOS=$(GOOS) GOARCH=$(GOARCH) \
	  go build -trimpath -ldflags "$(LDFLAGS)" -o $(DIST)/$(BIN)$(EXT) $(PKG)
	@echo "✔ $(DIST)/$(BIN)$(EXT)  ($$(du -h $(DIST)/$(BIN)$(EXT) | cut -f1))"

dist: build test-db ## 构建发行包：可执行文件 + 测试数据库 + README
	@cp README.md $(DIST)/README.md
	@echo
	@echo "▍发行包已就绪："
	@find $(DIST) -type f | sort | sed 's/^/  /'
	@echo
	@echo "  运行：cd $(DIST) && ./$(BIN)$(EXT)"

test-db: build ## 重建测试数据库 dist/data/pet.db（默认 1000 条模拟数据）
	@mkdir -p $(DIST)/data
	@rm -f $(DIST)/data/pet.db $(DIST)/data/pet.db.tmp
	@echo "▍生成测试数据库（$(SEED) 条模拟数据）…"
	@seed_bin="$(DIST)/$(BIN)$(EXT)"; temp_seed=""; pid=""; \
	if [ "$(GOOS)/$(GOARCH)" != "$(HOST_GOOS)/$(HOST_GOARCH)" ]; then \
	  temp_seed="$$(mktemp "$${TMPDIR:-/tmp}/$(BIN)-seed.XXXXXX")"; \
	  CGO_ENABLED=0 GOOS=$(HOST_GOOS) GOARCH=$(HOST_GOARCH) go build -trimpath -ldflags "$(LDFLAGS)" -o "$$temp_seed" $(PKG); \
	  seed_bin="$$temp_seed"; \
	fi; \
	cleanup() { [ -n "$$pid" ] && kill "$$pid" 2>/dev/null || true; [ -n "$$pid" ] && wait "$$pid" 2>/dev/null || true; rm -f "$$temp_seed" $(DIST)/.seed.log; }; \
	trap cleanup EXIT INT TERM; \
	"$$seed_bin" -addr 127.0.0.1:18080 -db $(DIST)/data/pet.db \
	    -seed -count $(SEED) -no-color > $(DIST)/.seed.log 2>&1 & \
	pid=$$!; \
	for i in $$(seq 1 90); do \
	  if [ -f $(DIST)/data/pet.db ] && grep -q "已写入模拟数据" $(DIST)/.seed.log 2>/dev/null; then break; fi; \
	  sleep 1; \
	done; \
	if ! [ -f $(DIST)/data/pet.db ] || ! grep -q "已写入模拟数据" $(DIST)/.seed.log; then \
	  echo "✖ 测试数据库生成失败" >&2; exit 1; \
	fi; \
	echo "✔ $(DIST)/data/pet.db  ($$(du -h $(DIST)/data/pet.db | cut -f1))"; \
	cleanup; trap - EXIT INT TERM

run: ## 直接运行源码（默认 127.0.0.1:8080）
	go run . $(ARGS)

seed: ## 运行源码并写入 2000 条模拟数据
	go run . -seed -count 2000

vet: ## 静态检查（go vet）
	go vet ./...

fmt: ## 格式化代码
	gofmt -l -w .

tidy: ## 整理 go.mod
	go mod tidy

cross: ## 交叉编译到三大平台（输出到 dist/）
	@mkdir -p $(DIST)
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(DIST)/$(BIN)-windows-amd64.exe $(PKG)
	CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(DIST)/$(BIN)-linux-amd64 $(PKG)
	CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(DIST)/$(BIN)-macos-arm64 $(PKG)
	CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(DIST)/$(BIN)-macos-amd64 $(PKG)
	@echo "✔ 交叉编译完成："
	@ls -lh $(DIST) | awk 'NR>1{printf "  %-32s %s\n", $$9, $$5}'

clean: ## 清理构建产物
	rm -rf $(DIST)
	@echo "✔ 已清理 $(DIST)/"
