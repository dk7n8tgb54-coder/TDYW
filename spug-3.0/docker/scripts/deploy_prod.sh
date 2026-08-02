#!/bin/bash
# =============================================================================
# deploy_prod.sh - 生产服务器部署脚本
#
# 功能：加载镜像 -> 保存旧版本 -> 更新 compose -> 重启 -> 健康检查 -> 失败自动回滚
#
# 用法：
#   bash deploy_prod.sh <tar文件名>
#   例如：bash deploy_prod.sh tdyw_20260802-123.ta
#
# 前提：
#   1. tar 文件已拷到本机（与 deploy_prod.sh 同目录或指定路径）
#   2. docker-compose.yml 和 .env 在本机 docker/ 目录下
#   3. tdyw 容器正在运行
# =============================================================================
set -euo pipefail

# ---------- 路径解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 如果脚本在 docker/scripts/ 下，DOCKER_DIR 是上级；如果直接在服务器上，DOCKER_DIR 是当前目录
if [ -f "${SCRIPT_DIR}/../docker-compose.yml" ]; then
    DOCKER_DIR="$(dirname "$SCRIPT_DIR")"
elif [ -f "${SCRIPT_DIR}/docker-compose.yml" ]; then
    DOCKER_DIR="$SCRIPT_DIR"
else
    echo "[FATAL] 找不到 docker-compose.yml"
    exit 1
fi
COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yml"
STATE_FILE="${DOCKER_DIR}/.last_deployed_image"
DEPLOY_LOG="${DOCKER_DIR}/.deploy_log"

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

# ---------- 参数检查 ----------
if [ -z "${1:-}" ]; then
    echo "用法: bash deploy_prod.sh <tar文件名>"
    echo "例如: bash deploy_prod.sh tdyw_20260802-123.tar"
    echo ""
    echo "可用 tar 文件："
    ls -lh "${SCRIPT_DIR}"/tdyw_*.tar 2>/dev/null || echo "  当前目录无 tar 文件"
    exit 1
fi

TAR_NAME="$1"
# 支持：文件名、相对路径、绝对路径
if [ -f "$TAR_NAME" ]; then
    TAR_FILE="$TAR_NAME"
elif [ -f "${SCRIPT_DIR}/${TAR_NAME}" ]; then
    TAR_FILE="${SCRIPT_DIR}/${TAR_NAME}"
else
    fatal "找不到 tar 文件: $TAR_NAME"
fi

info "tar 文件: ${TAR_FILE}"

# ---------- docker-compose 命令 ----------
if command -v docker-compose &>/dev/null; then
    DC="docker-compose"
elif docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
else
    fatal "未找到 docker-compose 或 docker compose"
fi

# ---------- 加载镜像 ----------
info "加载镜像..."
docker load -i "$TAR_FILE"
ok "镜像加载完成"

# 从 tar 文件名提取镜像 tag
# tdyw_20260802-123.tar -> tdyw:20260802-123
IMAGE_TAG=$(docker load -i "$TAR_FILE" 2>&1 | grep "Loaded image" | head -1 | sed 's/Loaded image: //')
if [ -z "$IMAGE_TAG" ]; then
    # 如果无法从输出提取，从文件名推断
    BASENAME="${TAR_NAME##*/}"
    BASENAME="${BASENAME%.tar}"
    IMAGE_TAG="tdyw:${BASENAME#tdyw_}"
fi
info "镜像 tag: ${IMAGE_TAG}"

# ---------- 保存当前版本（回滚用）----------
CURRENT_IMAGE=$(docker inspect --format='{{.Config.Image}}' tdyw 2>/dev/null || echo "")
if [ -z "$CURRENT_IMAGE" ]; then
    warn "tdyw 容器未运行，无法记录回滚版本"
    CURRENT_IMAGE="none"
fi
info "当前运行镜像: ${CURRENT_IMAGE}"
echo "$CURRENT_IMAGE" > "$STATE_FILE"
info "已保存当前版本（回滚用）"

# ---------- 更新 docker-compose.yml ----------
info "更新 docker-compose.yml 镜像 tag..."
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
    CONT_STATE=$(docker inspect --format='{{.State.Status}}' tdyw 2>/dev/null || echo "none")
    if [ "$CONT_STATE" = "exited" ] || [ "$CONT_STATE" = "dead" ]; then
        echo -e "${RED}[FATAL]${NC} 容器已退出（状态: ${CONT_STATE}）"
        echo "容器日志（最后 30 行）："
        docker logs --tail 30 tdyw 2>&1
        echo ""
        echo "=========================================="
        echo "  自动回滚到 ${CURRENT_IMAGE}"
        echo "=========================================="
        bash "${SCRIPT_DIR}/rollback.sh" --auto || true
        fatal "发布失败，已回滚"
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
    bash "${SCRIPT_DIR}/rollback.sh" --auto || true
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
echo "$(date '+%Y-%m-%d %H:%M:%S') | DEPLOY ${IMAGE_TAG} | prev:${CURRENT_IMAGE}" >> "$DEPLOY_LOG"

# ---------- 完成 ----------
echo ""
echo "=========================================="
ok "部署完成"
echo "=========================================="
echo "  镜像:   ${IMAGE_TAG}"
echo "  回滚到: ${CURRENT_IMAGE}"
echo ""
echo "  回滚命令: bash rollback.sh"
echo "  监控命令: bash post_deploy_watch.sh"
echo "=========================================="
