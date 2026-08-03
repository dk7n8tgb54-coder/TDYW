#!/bin/bash
# =============================================================================
# build.sh - 构建镜像并导出（在开发机上运行）
#
# 功能：git 检查 -> Django check -> 迁移检查 -> 构建镜像 -> 导出 tar 文件
#
# 用法：
#   wsl bash -c '/mnt/e/TDYW/spug-3.0/docker/scripts/build.sh'
#
# 产出：
#   /mnt/e/TDYW/dyw-server/tdyw_YYYYMMDD-N.ta
#
# 后续步骤：
#   1. 将 tar 文件拷到生产服务器
#   2. 在生产服务器运行 deploy_prod.sh
# =============================================================================
set -euo pipefail

# ---------- 路径解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$DOCKER_DIR")"
OUTPUT_DIR="/mnt/e/TDYW/dyw-server"

# ---------- 颜色输出 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fatal() { echo -e "${RED}[FATAL]${NC} $*"; exit 1; }
"""
# ---------- 前置检查 ----------
info "前置检查..."

# 1. git 工作区干净
cd "$PROJECT_DIR"
if ! git diff --quiet || ! git diff --cached --quiet; then
    fatal "git 工作区有未提交改动，请先 commit 或 stash"
fi

GIT_SHA=$(git rev-parse --short HEAD)
GIT_COUNT=$(git rev-list --count HEAD)
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
TAG_DATE=$(date +%Y%m%d)
IMAGE_TAG="tdyw:${TAG_DATE}-${GIT_COUNT}"
GIT_TAG="tdyw:git-${GIT_SHA}"
TAR_FILE="${OUTPUT_DIR}/tdyw_${TAG_DATE}-${GIT_COUNT}.tar"

info "分支: ${GIT_BRANCH}  commit: ${GIT_SHA}"
info "新镜像 tag: ${IMAGE_TAG}"
info "导出文件: ${TAR_FILE}"

# 2. Dockerfile 存在
if [ ! -f "${DOCKER_DIR}/Dockerfile" ]; then
    fatal "Dockerfile 不存在: ${DOCKER_DIR}/Dockerfile"
fi

# 3. 输出目录存在
mkdir -p "$OUTPUT_DIR"
"""
# ---------- Django check（用 tdyw 容器）----------
if docker inspect tdyw &>/dev/null; then
    info "运行 Django check（tdyw 容器）..."
    if docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
        python manage.py check --tag compatibility 2>&1; then
        ok "Django check 通过"
    else
        warn "Django check 有警告，继续构建（不阻塞）"
    fi
else
    warn "tdyw 容器不存在，跳过 Django check"
fi

# ---------- 迁移检查 ----------
if docker inspect tdyw &>/dev/null; then
    info "检查待执行迁移..."
    PENDING=$(docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
        python manage.py showmigrations --list 2>&1 | grep -c '\[ \]' || true)

    if [ "$PENDING" -gt 0 ]; then
        warn "有 ${PENDING} 个待执行迁移"
        warn "待执行迁移列表："
        docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
            python manage.py showmigrations --list 2>&1 | grep "\[ \]" | head -20 || true

        # 扫描破坏性操作
        info "扫描迁移文件中的破坏性操作..."
        DESTRUCTIVE=$(docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
            bash -c "grep -rl 'RemoveField\|AlterField\|DeleteModel\|RemoveIndex\|AlterUniqueTogether' apps/*/migrations/*.py 2>/dev/null | tail -5" || echo "")

        if [ -n "$DESTRUCTIVE" ]; then
            warn "发现含破坏性操作的迁移文件："
            echo "$DESTRUCTIVE" | while read -r f; do
                warn "  $f"
            done
            warn "破坏性迁移需手动两步操作（先删代码引用不删字段，观察后再删字段）"
            warn "确认继续构建？(Ctrl+C 取消，回车继续)"
            read -r < /dev/tty || true
        fi
    else
        ok "无待执行迁移"
    fi
fi
"""
# ---------- 构建镜像 ----------
info "构建镜像 ${IMAGE_TAG}..."
cd "$PROJECT_DIR"
if docker build -t "$IMAGE_TAG" -t "$GIT_TAG" -t tdyw:latest -f docker/Dockerfile .; then
    ok "镜像构建成功"
else
    fatal "镜像构建失败"
fi

# ---------- 导出 tar 文件 ----------
info "导出镜像到 ${TAR_FILE}..."
if docker save -o "$TAR_FILE" "$IMAGE_TAG" "$GIT_TAG"; then
    FILE_SIZE=$(du -h "$TAR_FILE" | awk '{print $1}')
    ok "导出成功: ${TAR_FILE} (${FILE_SIZE})"
else
    fatal "导出失败"
fi

# ---------- 完成 ----------
echo ""
echo "=========================================="
ok "构建完成"
echo "=========================================="
echo "  镜像:   ${IMAGE_TAG}"
echo "  Git:    ${GIT_SHA} (${GIT_BRANCH})"
echo "  文件:   ${TAR_FILE}"
echo "  大小:   ${FILE_SIZE}"
echo ""
echo "  下一步："
echo "  1. 拷贝 tar 文件到生产服务器"
echo "  2. 在生产服务器运行:"
echo "     bash deploy_prod.sh ${TAR_FILE##*/}"
echo "=========================================="
"""