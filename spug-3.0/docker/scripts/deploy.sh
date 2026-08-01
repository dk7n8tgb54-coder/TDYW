#!/bin/bash
# =============================================================================
# deploy.sh - 发布脚本
#
# 功能：构建新镜像 -> 保存当前版本 -> 更新 compose -> 重启 -> 健康检查 -> 失败自动回滚
#
# 用法：
#   wsl bash -c '/mnt/e/TDYW/spug-3.0/docker/scripts/deploy.sh'
#   或在 WSL 终端中：
#   /mnt/e/TDYW/spug-3.0/docker/scripts/deploy.sh
#
# 前提：
#   1. git 工作区干净（无未提交改动）
#   2. docker/.env 已配置
#   3. tdyw 容器正在运行
# =============================================================================
set -euo pipefail

# ---------- 路径解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$DOCKER_DIR")"
COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yml"
ENV_FILE="${DOCKER_DIR}/.env"
STATE_FILE="${DOCKER_DIR}/.last_deployed_image"
DEPLOY_LOG="${DOCKER_DIR}/.deploy_log"

# ---------- 加载环境变量 ----------
if [ ! -f "$ENV_FILE" ]; then
    echo "[FATAL] 环境文件不存在: $ENV_FILE"
    exit 1
fi
set -a
source "$ENV_FILE"
set +a

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

info "分支: ${GIT_BRANCH}  commit: ${GIT_SHA}"
info "新镜像 tag: ${IMAGE_TAG}  (alias: ${GIT_TAG})"

# 2. tdyw 容器正在运行
CURRENT_IMAGE=$(docker inspect --format='{{.Config.Image}}' tdyw 2>/dev/null || echo "")
if [ -z "$CURRENT_IMAGE" ]; then
    warn "tdyw 容器未运行，无法记录回滚版本"
    CURRENT_IMAGE="none"
fi
info "当前运行镜像: ${CURRENT_IMAGE}"

# 3. Dockerfile 存在
if [ ! -f "${DOCKER_DIR}/Dockerfile" ]; then
    fatal "Dockerfile 不存在: ${DOCKER_DIR}/Dockerfile"
fi

# 4. docker-compose 命令
if command -v docker-compose &>/dev/null; then
    DC="docker-compose"
elif docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
else
    fatal "未找到 docker-compose 或 docker compose"
fi
info "compose 命令: ${DC}"

# ---------- 保存当前版本（回滚用）----------
echo "$CURRENT_IMAGE" > "$STATE_FILE"
info "已保存当前版本到 ${STATE_FILE}（回滚用）"

# ---------- Django check（可选，用 tdyw-test 容器）----------
if docker inspect tdyw-test &>/dev/null; then
    info "运行 Django check（tdyw-test 容器）..."
    if docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
        python manage.py check --tag compatibility 2>&1; then
        ok "Django check 通过"
    else
        warn "Django check 有警告，继续发布（不阻塞）"
    fi
else
    warn "tdyw-test 容器不存在，跳过 Django check"
fi

# ---------- 构建新镜像 ----------
info "构建新镜像 ${IMAGE_TAG}..."
cd "$PROJECT_DIR"
if docker build -t "$IMAGE_TAG" -t "$GIT_TAG" -t tdyw:latest -f docker/Dockerfile .; then
    ok "镜像构建成功"
else
    fatal "镜像构建失败"
fi

# ---------- 更新 docker-compose.yml 中的镜像 tag ----------
info "更新 docker-compose.yml 镜像 tag..."
# 只替换 tdyw 服务下未注释的 image: tdyw:xxx 行
sed -i "/^[[:space:]]*#.*image:/!s|^\([[:space:]]*\)image: tdyw:[0-9a-zA-Z._-]*|\1image: ${IMAGE_TAG}|" "$COMPOSE_FILE"
ok "docker-compose.yml 已更新为 ${IMAGE_TAG}"

# ---------- 重启容器 ----------
info "重启 tdyw 容器..."
cd "$DOCKER_DIR"
$DC -f docker-compose.yml up -d tdyw
ok "容器已启动"

# ---------- 健康检查 ----------
info "等待健康检查（最长 90 秒）..."
HEALTH_OK=false
for i in $(seq 1 90); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' tdyw 2>/dev/null || echo "none")
    if [ "$STATUS" = "healthy" ]; then
        HEALTH_OK=true
        ok "容器健康（第 ${i}s）"
        break
    fi
    # 检查容器是否已退出
    CONT_STATE=$(docker inspect --format='{{.State.Status}}' tdyw 2>/dev/null || echo "none")
    if [ "$CONT_STATE" = "exited" ] || [ "$CONT_STATE" = "dead" ]; then
        fatal "容器已退出（状态: ${CONT_STATE}），执行回滚..."
    fi
    sleep 1
done

if [ "$HEALTH_OK" = "false" ]; then
    echo -e "${RED}[FATAL]${NC} 健康检查超时！最后状态: ${STATUS}"
    echo "容器日志（最后 30 行）："
    docker logs --tail 30 tdyw 2>&1
    echo ""
    echo "=========================================="
    echo "  自动回滚到 ${CURRENT_IMAGE}"
    echo "=========================================="
    bash "${SCRIPT_DIR}/rollback.sh" --auto
    fatal "发布失败，已回滚"
fi

# ---------- 检查迁移错误 ----------
info "检查迁移日志..."
MIGRATE_LOG=$(docker logs tdyw 2>&1 | grep -i "migrate\|迁移" || true)
if echo "$MIGRATE_LOG" | grep -qi "error\|fail\|traceback"; then
    warn "迁移日志中可能有错误："
    echo "$MIGRATE_LOG" | tail -10
    warn "请手动检查：docker logs tdyw 2>&1 | grep -A5 -i migrate"
else
    ok "迁移日志正常"
fi

# ---------- 记录发布日志 ----------
echo "$(date '+%Y-%m-%d %H:%M:%S') | DEPLOY ${IMAGE_TAG} | git:${GIT_SHA} | branch:${GIT_BRANCH} | prev:${CURRENT_IMAGE}" >> "$DEPLOY_LOG"

# ---------- 完成 ----------
echo ""
echo "=========================================="
ok "发布完成"
echo "=========================================="
echo "  镜像:     ${IMAGE_TAG}"
echo "  Git:      ${GIT_SHA} (${GIT_BRANCH})"
echo "  回滚到:   ${CURRENT_IMAGE}"
echo ""
echo "  回滚命令: bash ${SCRIPT_DIR}/rollback.sh"
echo "  监控命令: bash ${SCRIPT_DIR}/post_deploy_watch.sh"
echo "=========================================="
