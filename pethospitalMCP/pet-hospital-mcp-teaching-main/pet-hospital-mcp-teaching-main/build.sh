#!/usr/bin/env bash
# 构建宠物医院系统，并把可执行文件、测试数据库、说明文档放进 dist/。
#
# 用法：
#   ./build.sh              # 编译 + 准备测试数据库（1000 条模拟数据）
#   ./build.sh -c 3000      # 指定测试数据库的模拟数据条数
#   ./build.sh -n           # 只编译，不生成测试数据库
#   ./build.sh --clean      # 清理 dist/
set -euo pipefail

cd "$(dirname "$0")"

OUT_DIR="dist"
BIN_NAME="pethospital"
SEED_COUNT=1000
MAKE_DB=1

while [ $# -gt 0 ]; do
  case "$1" in
  -c | --count)
    SEED_COUNT="${2:-1000}"
    shift 2
    ;;
  -n | --no-db)
    MAKE_DB=0
    shift
    ;;
  --clean)
    rm -rf "$OUT_DIR"
    echo "✔ 已清理 $OUT_DIR/"
    exit 0
    ;;
  -h | --help)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    echo "未知参数: $1（用 --help 查看用法）" >&2
    exit 1
    ;;
  esac
done

# 目标平台：默认当前平台，可用 GOOS/GOARCH 环境变量覆盖
GOOS="${GOOS:-$(go env GOOS)}"
GOARCH="${GOARCH:-$(go env GOARCH)}"
EXT=""
[ "$GOOS" = "windows" ] && EXT=".exe"

mkdir -p "$OUT_DIR/data"

echo "▍编译可执行文件"
echo "  目标平台: ${GOOS}/${GOARCH}"
CGO_ENABLED=0 GOOS="$GOOS" GOARCH="$GOARCH" \
  go build -trimpath -ldflags "-s -w" -o "$OUT_DIR/${BIN_NAME}${EXT}" .
echo "  ✔ $OUT_DIR/${BIN_NAME}${EXT}  ($(du -h "$OUT_DIR/${BIN_NAME}${EXT}" | cut -f1))"

if [ "$MAKE_DB" = "1" ]; then
  echo
  echo "▍生成测试数据库（${SEED_COUNT} 条模拟数据）"
  DB="$OUT_DIR/data/pet.db"
  rm -f "$DB" "$DB.tmp"
  HOST_GOOS="$(go env GOHOSTOS)"
  HOST_GOARCH="$(go env GOHOSTARCH)"
  SEED_BIN="$OUT_DIR/${BIN_NAME}${EXT}"
  TEMP_SEED_BIN=""
  if [ "$GOOS/$GOARCH" != "$HOST_GOOS/$HOST_GOARCH" ]; then
    TEMP_SEED_BIN="$(mktemp "${TMPDIR:-/tmp}/${BIN_NAME}-seed.XXXXXX")"
    CGO_ENABLED=0 GOOS="$HOST_GOOS" GOARCH="$HOST_GOARCH" \
      go build -trimpath -ldflags "-s -w" -o "$TEMP_SEED_BIN" .
    SEED_BIN="$TEMP_SEED_BIN"
  fi
  PID=""
  cleanup() {
    [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
    [ -n "$PID" ] && wait "$PID" 2>/dev/null || true
    rm -f "$TEMP_SEED_BIN" "$OUT_DIR/.seed.log"
  }
  trap cleanup EXIT INT TERM
  # 让程序自己建库并灌数据，保证文件格式与代码完全一致。
  # 交叉编译时用宿主平台临时程序灌库，目标 .exe 不会在 macOS/Linux 上运行。
  PORT=18080
  "$SEED_BIN" -addr "127.0.0.1:${PORT}" -db "$DB" \
    -seed -count "$SEED_COUNT" -no-color >"$OUT_DIR/.seed.log" 2>&1 &
  PID=$!
  # 等待数据库生成完成（最多 90 秒）
  for _ in $(seq 1 90); do
    if [ -f "$DB" ] && grep -q "已写入模拟数据" "$OUT_DIR/.seed.log" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if [ -f "$DB" ] && grep -q "已写入模拟数据" "$OUT_DIR/.seed.log"; then
    echo "  ✔ $DB  ($(du -h "$DB" | cut -f1))"
  else
    echo "  ✖ 测试数据库生成失败" >&2
    exit 1
  fi
  cleanup
  trap - EXIT INT TERM
fi

# 附带说明文档
[ -f README.md ] && cp README.md "$OUT_DIR/README.md"

echo
echo "▍完成，dist/ 内容："
find "$OUT_DIR" -type f | sort | sed 's/^/  /'
echo
echo "  运行方式："
echo "    cd $OUT_DIR && ./${BIN_NAME}${EXT}"
echo "    浏览器打开 http://127.0.0.1:8080/"
