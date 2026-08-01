#!/bin/bash
# =============================================================================
# rollback.sh - 回滚脚本
#
# 功能：读取上次部署的镜像 tag -> 更新 compose -> 重启 -> 健康检查
#       如果没有记录，列出可用镜像供选择
#
# 用法：
#   wsl bash -c '/mnt/e/TDYW/spug-3.0/docker/scripts/rollback.sh'
#   自动回滚（由 deploy.sh 调用，不交互）：
#   bash rollback.sh --auto
#
# 前提：
#   1. .last_deployed_image 文件存在（由 deploy.sh 生成）
#   2. 或手动指定镜像 tag
# =============================================================================
set -euo pipefail

# ---------- 路径解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$DOCKER_DIR")"
COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yml"
STATE_FILE="${DOCKER_DIR}/.last_deployed_image"
DEPLOY_LOG="${DOCKER_DIR}/.deploy_log"
AUTO_MODE=false

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

# ---------- 参数解析 ----------
if [ "${1:-}" = "--auto" ]; then
    AUTO_MODE=true
fi

# ---------- docker-compose 命令 ----------
if command -v docker-compose &>/dev/null; then
    DC="docker-compose"
elif docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
else
    fatal "未找到 docker-compose 或 docker compose"
fi

# ---------- 确定回滚目标镜像 ----------
TARGET_IMAGE=""

if [ -f "$STATE_FILE" ]; then
    TARGET_IMAGE=$(cat "$STATE_FILE")
    info "上次部署镜像: ${TARGET_IMAGE}"
fi

# 如果没有记录或记录是 none，交互选择
if [ -z "$TARGET_IMAGE" ] || [ "$TARGET_IMAGE" = "none" ]; then
    if [ "$AUTO_MODE" = "true" ]; then
        fatal "自动回滚模式但没有上次部署记录，无法回滚"
    fi

    echo ""
    info "未找到上次部署记录，可用镜像列表："
    echo "--------------------------------------------"
    docker images tdyw --format "table {{.Tag}}\t{{.CreatedAt}}\t{{.Size}}" | head -20
    echo "--------------------------------------------"
    echo ""
    read -p "输入要回滚的 tag（不含 tdyw: 前缀）: " USER_TAG
    if [ -z "$USER_TAG" ]; then
        fatal "未输入 tag"
    fi
    TARGET_IMAGE="tdyw:${USER_TAG}"
fi

# ---------- 验证镜像存在 ----------
if ! docker image inspect "$TARGET_IMAGE" &>/dev/null; then
    fatal "镜像不存在: ${TARGET_IMAGE}"
    if [ "$AUTO_MODE" = "false" ]; then
        info "可用镜像："
        docker images tdyw --format "{{.Tag}}" | head -10
    fi
    exit 1
fi

# ---------- 确认（交互模式）----------
CURRENT_IMAGE=$(docker inspect --format='{{.Config.Image}}' tdyw 2>/dev/null || echo "none")
if [ "$AUTO_MODE" = "false" ]; then
    echo ""
    echo "=========================================="
    echo "  当前镜像: ${CURRENT_IMAGE}"
    echo "  回滚到:   ${TARGET_IMAGE}"
    echo "=========================================="
    echo ""
    read -p "确认回滚？(y/N): " CONFIRM
    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        info "已取消"
        exit 0
    fi
fi

# ---------- 执行回滚 ----------
info "开始回滚到 ${TARGET_IMAGE}..."

# 更新 docker-compose.yml 中的镜像 tag
sed -i "/^[[:space:]]*#.*image:/!s|^\([[:space:]]*\)image: tdyw:[0-9a-zA-Z._-]*|\1image: ${TARGET_IMAGE}|" "$COMPOSE_FILE"
ok "docker-compose.yml 已更新为 ${TARGET_IMAGE}"

# 重启容器
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
        echo -e "${RED}[FATAL]${NC} 回滚后容器已退出！"
        echo "容器日志（最后 30 行）："
        docker logs --tail 30 tdyw 2>&1
        fatal "回滚失败，请手动检查"
    fi
    sleep 1
done

if [ "$HEALTH_OK" = "false" ]; then
    echo -e "${RED}[FATAL]${NC} 回滚后健康检查超时！最后状态: ${STATUS}"
    echo "容器日志（最后 30 行）："
    docker logs --tail 30 tdyw 2>&1
    fatal "回滚后健康检查失败，请手动检查"
fi

# ---------- 记录回滚日志 ----------
echo "$(date '+%Y-%m-%d %H:%M:%S') | ROLLBACK to ${TARGET_IMAGE} | from:${CURRENT_IMAGE}" >> "$DEPLOY_LOG"

# ---------- 更新回滚状态文件 ----------
# 回滚后，当前运行的镜像就是新的"上次部署"镜像
echo "$CURRENT_IMAGE" > "$STATE_FILE"

# ---------- 完成 ----------
echo ""
echo "=========================================="
ok "回滚完成"
echo "=========================================="
echo "  当前镜像: ${TARGET_IMAGE}"
echo "  回滚自:   ${CURRENT_IMAGE}"
echo ""
echo "  注意: 如果回滚涉及数据库迁移变更，"
echo "  可能需要手动回滚迁移:"
echo "  docker exec -e PYTHONIOENCODING=utf-8 \\"
echo "    -w /data/spug/spug_api tdyw \\"
echo "    python manage.py migrate <app> <migration_name>"
echo "=========================================="
