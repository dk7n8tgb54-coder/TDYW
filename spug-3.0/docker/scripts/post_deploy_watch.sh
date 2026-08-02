#!/bin/bash
# =============================================================================
# post_deploy_watch.sh - 发布后监控脚本
#
# 功能：发布后持续监控容器健康、5xx 错误、Celery 失败、磁盘空间
#       任何指标超阈值则告警，建议回滚
#
# 用法：
#   wsl bash -c '/mnt/e/TDYW/spug-3.0/docker/scripts/post_deploy_watch.sh'
#   指定监控时长（默认 300 秒）：
#   bash post_deploy_watch.sh 600
#
# 阈值可在脚本头部调整
# =============================================================================
set -euo pipefail

# ---------- 路径解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"

# ---------- 配置 ----------
WATCH_SECONDS="${1:-300}"          # 监控时长，默认 300 秒（5 分钟）
CHECK_INTERVAL=30                  # 检查间隔，秒
THRESHOLD_5XX=5                    # 30 秒窗口内 5xx 错误阈值
THRESHOLD_CELERY_FAIL=3            # 30 秒窗口内 Celery 失败阈值
THRESHOLD_DISK_PCT=90              # 磁盘使用率告警阈值（%）
CONTAINER_NAME="tdyw"

# ---------- 颜色输出 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()      { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
alert()   { echo -e "${RED}[ALERT]${NC} $*"; }

# ---------- 前置检查 ----------
if ! docker inspect "$CONTAINER_NAME" &>/dev/null; then
    alert "容器 ${CONTAINER_NAME} 不存在！"
    exit 1
fi

CURRENT_IMAGE=$(docker inspect --format='{{.Config.Image}}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")

echo ""
echo "=========================================="
echo "  发布后监控"
echo "=========================================="
echo "  镜像:   ${CURRENT_IMAGE}"
echo "  时长:   ${WATCH_SECONDS}s (${CHECK_INTERVAL}s 间隔)"
echo "  阈值:   5xx>${THRESHOLD_5XX} / celery_fail>${THRESHOLD_CELERY_FAIL} / migrate_err>0 / disk>${THRESHOLD_DISK_PCT}%"
echo "=========================================="
echo ""

# 统计基线（防止历史错误被计入）
BASELINE_5XX=0
BASELINE_CELERY=0

# ---------- 监控循环 ----------
START_TIME=$SECONDS
END_TIME=$((SECONDS + WATCH_SECONDS))
ITERATION=0
ALERT_COUNT=0
MAX_ALERTS=3    # 连续告警 3 次建议回滚

while [ $SECONDS -lt $END_TIME ]; do
    ITERATION=$((ITERATION + 1))
    NOW=$(date '+%H:%M:%S')

    # 1. 容器健康状态
    HEALTH=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "none")
    CONT_STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "none")

    # 2. 5xx 错误计数（最近 30 秒）
    ERR_5XX=$(docker logs --since 30s "$CONTAINER_NAME" 2>&1 | grep -c "500 Internal\|Traceback\|ERROR" || true)

    # 3. Celery 失败计数（最近 30 秒）
    CELERY_FAIL=$(docker logs --since 30s "$CONTAINER_NAME" 2>&1 | grep -c "Task.*failed\|celery.*error\|WorkerLostError" || true)

    # 3.5 迁移错误检查（entrypoint.sh 吞掉的迁移失败 + DB schema 不匹配）
    MIGRATE_ERR=$(docker logs --since 30s "$CONTAINER_NAME" 2>&1 | grep -c "迁移失败\|Migration failed\|OperationalError\|ProgrammingError\|IntegrityError\|column.*does not exist\|no such column\|table.*already exists" || true)

    # 4. 磁盘使用率
    DISK_PCT=$(df -h /var/lib/docker 2>/dev/null | awk 'NR==2{gsub("%",""); print $5}')
    # 如果上面取不到（WSL 路径不同），尝试 /mnt/e
    if [ -z "$DISK_PCT" ] || [ "$DISK_PCT" = "0" ]; then
        DISK_PCT=$(df -h /mnt/e 2>/dev/null | awk 'NR==2{gsub("%",""); print $5}')
    fi
    DISK_PCT=${DISK_PCT:-0}

    # 5. 容器内存使用
    MEM_USAGE=$(docker stats --no-stream --format "{{.MemUsage}}" "$CONTAINER_NAME" 2>/dev/null || echo "N/A")

    # ---------- 输出状态行 ----------
    STATUS_LINE="${NOW} | health=${HEALTH} | 5xx=${ERR_5XX} | celery_fail=${CELERY_FAIL} | migrate_err=${MIGRATE_ERR} | disk=${DISK_PCT}% | mem=${MEM_USAGE}"

    # ---------- 告警判断 ----------
    ALERT_MSG=""

    if [ "$CONT_STATUS" != "running" ]; then
        ALERT_MSG="容器状态异常: ${CONT_STATUS}"
    elif [ "$HEALTH" != "healthy" ]; then
        ALERT_MSG="健康检查未通过: ${HEALTH}"
    elif [ "$ERR_5XX" -gt "$THRESHOLD_5XX" ]; then
        ALERT_MSG="5xx/错误数过高: ${ERR_5XX} > ${THRESHOLD_5XX}"
    elif [ "$MIGRATE_ERR" -gt 0 ]; then
        ALERT_MSG="迁移/DB schema 错误: ${MIGRATE_ERR} 条（迁移失败或新代码与 DB 结构不匹配）"
    elif [ "$CELERY_FAIL" -gt "$THRESHOLD_CELERY_FAIL" ]; then
        ALERT_MSG="Celery 失败过多: ${CELERY_FAIL} > ${THRESHOLD_CELERY_FAIL}"
    elif [ "$DISK_PCT" -gt "$THRESHOLD_DISK_PCT" ]; then
        ALERT_MSG="磁盘使用率过高: ${DISK_PCT}% > ${THRESHOLD_DISK_PCT}%"
    fi

    if [ -n "$ALERT_MSG" ]; then
        alert "${STATUS_LINE}"
        alert "  -> ${ALERT_MSG}"
        ALERT_COUNT=$((ALERT_COUNT + 1))

        if [ "$ALERT_COUNT" -ge "$MAX_ALERTS" ]; then
            echo ""
            alert "=========================================="
            alert "  连续 ${MAX_ALERTS} 次告警！建议立即回滚"
            alert "=========================================="
            echo ""
            echo "最近 20 行容器日志："
            docker logs --tail 20 "$CONTAINER_NAME" 2>&1
            echo ""
            echo "回滚命令: bash ${SCRIPT_DIR}/rollback.sh"
            exit 2
        fi
    else
        ok "${STATUS_LINE}"
        ALERT_COUNT=0   # 恢复正常则重置告警计数
    fi

    # 等待下一轮
    REMAINING=$((END_TIME - SECONDS))
    if [ $REMAINING -gt $CHECK_INTERVAL ]; then
        sleep $CHECK_INTERVAL
    elif [ $REMAINING -gt 0 ]; then
        sleep $REMAINING
    fi
done

# ---------- 监控完成 ----------
ELAPSED=$((SECONDS - START_TIME))
echo ""
echo "=========================================="
ok "监控完成（${ELAPSED}s，${ITERATION} 轮检查）"
echo "=========================================="
echo "  镜像:   ${CURRENT_IMAGE}"
echo "  状态:   稳定运行"
echo ""
echo "  本次监控未发现异常，发布可视为成功"
echo "=========================================="
