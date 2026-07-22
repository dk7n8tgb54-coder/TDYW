#!/bin/bash
# ================================================================================
# 数据库监控告警脚本
# --------------------------------------------------------------------------------
# 通过 docker exec 连接 tdyw-db 容器内的 MySQL，执行以下检查并按阈值告警：
#   1. 单表行数 + 数据量监控（发现数据异常膨胀）
#   2. 慢查询日志统计（发现性能劣化）
#   3. 磁盘空间使用率（防止磁盘写满）
#   4. 连接数使用率（防止连接耗尽）
#
# 配套：docker/config/mysqlnew.cnf 已开 slow_query_log=1, long_query_time=1
#
# 用法：
#   ./db_monitor_alert.sh                 # 检查并输出报告
#   ./db_monitor_alert.sh --warn-only     # 仅输出告警项（cron 友好，无告警则静默）
#
# 定时任务示例（crontab -e，每周一 08:00 执行）：
#   0 8 * * 1  /path/to/db_monitor_alert.sh --warn-only >> /var/log/tdyw-db-monitor.log 2>&1
#
# 告警阈值在下方【阈值配置】区调整；超阈值项输出 [WARN] / [CRITICAL] 标记，
# 便于接入告警系统（grep CRITICAL 触发邮件/钉钉）。
# ================================================================================

set -euo pipefail

# ============================================
# 路径与容器配置（与 backups/mariadump_backup.sh 保持一致）
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_ENV_FILE="${PROJECT_ROOT}/docker/.env"
if [ ! -f "${DEFAULT_ENV_FILE}" ] && [ -f "/opt/docker/docker/.env" ]; then
    DEFAULT_ENV_FILE="/opt/docker/docker/.env"
fi
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"

DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
DB_USER="root"
DB_NAME="tdyw"
DB_PASSWORD=""

# 日志输出目录
TDYW_LOG_DIR="${TDYW_LOG_DIR:-/var/log/tdyw-backup}"
LOG_FILE="${LOG_FILE:-${TDYW_LOG_DIR}/db_monitor.log}"

# 慢查询日志路径（与 mysqlnew.cnf 的 slow_query_log_file 一致）
SLOW_LOG_PATH="/var/log/mysql/slow"

# ============================================
# 阈值配置（按本项目实际情况设定，可按需调整）
# ============================================
# 单表行数
TABLE_ROWS_WARN=1000000       # 100 万行 黄色预警
TABLE_ROWS_CRITICAL=5000000   # 500 万行 橙色预警
# 单表数据量（MB）
TABLE_SIZE_WARN_MB=500        # 500MB 黄色
TABLE_SIZE_CRITICAL_MB=2000   # 2GB   橙色
# 慢查询（每小时新增条数）
SLOW_PER_HOUR_WARN=50         # 每小时 >50 条慢查询 黄色
SLOW_PER_HOUR_CRITICAL=200    # 每小时 >200 条 橙色
# 磁盘使用率（%）
DISK_WARN_PCT=75
DISK_CRITICAL_PCT=90
# 连接数使用率（占 max_connections 的 %）
CONN_WARN_PCT=70              # 300 连接下约 210
CONN_CRITICAL_PCT=90          # 300 连接下约 270

# 告警计数
WARN_COUNT=0
CRITICAL_COUNT=0
WARN_ONLY=0

# ============================================
# 日志函数
# ============================================
log() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${ts}] ${msg}" 2>/dev/null || true
}

ts() { date '+%Y-%m-%d %H:%M:%S'; }

emit() {
    # $1=级别 $2=内容
    if [ "${WARN_ONLY}" -eq 1 ] && [ "$1" = "INFO" ]; then
        return
    fi
    echo "[$(ts)] [$1] $2"
    case "$1" in
        WARN)     WARN_COUNT=$((WARN_COUNT + 1)) ;;
        CRITICAL) CRITICAL_COUNT=$((CRITICAL_COUNT + 1)) ;;
    esac
}

# ============================================
# 加载 docker/.env
# ============================================
load_env() {
    if [ -f "${ENV_FILE}" ]; then
        while IFS='=' read -r key value || [ -n "${key}" ]; do
            key="${key%%#*}"
            key="$(echo "${key}" | xargs)"
            value="$(echo "${value}" | xargs)"
            [ -z "${key}" ] && continue
            case "${key}" in
                MYSQL_ROOT_PASSWORD) DB_PASSWORD="${value}" ;;
                MYSQL_DATABASE)      DB_NAME="${value}" ;;
            esac
        done < "${ENV_FILE}"
    fi
    if [ -z "${DB_PASSWORD}" ]; then
        emit CRITICAL "未能从 ${ENV_FILE} 读取 MYSQL_ROOT_PASSWORD"
        exit 1
    fi
}

# 执行 MySQL 查询（容器内），抑制密码警告
# 用法: run_sql "SELECT ..."
run_sql() {
    docker exec "${DB_CONTAINER}" \
        mariadb -u"${DB_USER}" -p"${DB_PASSWORD}" \
        -N -B --default-character-set=utf8mb4 \
        "${DB_NAME}" 2>/dev/null <<< "$1"
}

# ============================================
# 前置检查
# ============================================
preflight() {
    if ! command -v docker >/dev/null 2>&1; then
        emit CRITICAL "未找到 docker 命令"
        exit 1
    fi
    local state
    state="$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}" 2>/dev/null || echo "false")"
    if [ "${state}" != "true" ]; then
        emit CRITICAL "容器 ${DB_CONTAINER} 未运行"
        exit 1
    fi
    mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || true
}

# ============================================
# 检查 1：单表行数 + 数据量
# ============================================
check_table_sizes() {
    emit INFO "========== 检查 1：单表行数与数据量 =========="
    # 输出格式：table_name \t rows \t data_mb \t index_mb
    local result
    result="$(run_sql "
        SELECT table_name, IFNULL(table_rows,0),
               ROUND((data_length)/1024/1024,2),
               ROUND((index_length)/1024/1024,2)
        FROM information_schema.tables
        WHERE table_schema='${DB_NAME}'
          AND table_type='BASE TABLE'
        ORDER BY IFNULL(table_rows,0) DESC;
    ")" || { emit WARN "查询 information_schema 失败"; return; }

    if [ -z "${result}" ]; then
        emit WARN "未查询到任何表，请确认 DB_NAME=${DB_NAME}"
        return
    fi

    emit INFO "行数TOP10（表名 / 行数 / 数据MB / 索引MB）:"
    echo "${result}" | head -10 | while IFS=$'\t' read -r name rows data_mb idx_mb; do
        printf "    %-40s %12s %10s %10s\n" "${name}" "${rows}" "${data_mb}" "${idx_mb}"
    done

    # 阈值判断
    echo "${result}" | while IFS=$'\t' read -r name rows data_mb idx_mb; do
        [ -z "${name}" ] && continue
        rows="${rows:-0}"
        data_mb="${data_mb:-0}"
        # 行数告警
        if [ "${rows}" -ge "${TABLE_ROWS_CRITICAL}" ] 2>/dev/null; then
            emit CRITICAL "表 ${name} 行数 ${rows} 超过橙色阈值 ${TABLE_ROWS_CRITICAL}"
        elif [ "${rows}" -ge "${TABLE_ROWS_WARN}" ] 2>/dev/null; then
            emit WARN "表 ${name} 行数 ${rows} 超过黄色阈值 ${TABLE_ROWS_WARN}"
        fi
        # 数据量告警（data_mb 是浮点数，用 awk 比较）
        local over
        over=$(awk "BEGIN{print (${data_mb}>=${TABLE_SIZE_CRITICAL_MB})?1:0}")
        if [ "${over}" = "1" ]; then
            emit CRITICAL "表 ${name} 数据量 ${data_mb}MB 超过橙色阈值 ${TABLE_SIZE_CRITICAL_MB}MB"
        else
            over=$(awk "BEGIN{print (${data_mb}>=${TABLE_SIZE_WARN_MB})?1:0}")
            if [ "${over}" = "1" ]; then
                emit WARN "表 ${name} 数据量 ${data_mb}MB 超过黄色阈值 ${TABLE_SIZE_WARN_MB}MB"
            fi
        fi
    done
}

# ============================================
# 检查 2：慢查询日志统计
# ============================================
check_slow_queries() {
    emit INFO "========== 检查 2：慢查询日志 =========="
    # 检查慢查询日志文件是否存在
    if ! docker exec "${DB_CONTAINER}" test -f "${SLOW_LOG_PATH}" 2>/dev/null; then
        emit WARN "慢查询日志 ${SLOW_LOG_PATH} 不存在（可能未启用 slow_query_log）"
        return
    fi

    # 慢查询总行数（粗略反映历史累计量）
    local total_lines
    total_lines="$(docker exec "${DB_CONTAINER}" wc -l < "${SLOW_LOG_PATH}" 2>/dev/null | xargs)"
    total_lines="${total_lines:-0}"
    emit INFO "慢查询日志总行数: ${total_lines}"

    # 统计最近 1 小时内的慢查询条数
    # MariaDB slow log 每条查询以 "# Time: YYMMDD HH:MM:SS" 开头
    local one_hour_ago now_ts recent_count
    one_hour_ago="$(date -d '1 hour ago' '+%y%m%d %H:%M:%S' 2>/dev/null || date -v-1H '+%y%m%d %H:%M:%S' 2>/dev/null || echo '')"
    if [ -n "${one_hour_ago}" ]; then
        # 提取最近1小时的 # Time 行数作为慢查询条数估算
        recent_count="$(docker exec "${DB_CONTAINER}" awk -v cutoff="${one_hour_ago}" '
            /^# Time:/ {
                # 取该行时间部分比较（格式 # Time: 260722 08:00:00）
                ts = substr($0, index($0,":")+2)
                if (ts >= cutoff) cnt++
            }
            END { print cnt+0 }
        ' "${SLOW_LOG_PATH}" 2>/dev/null | xargs)"
        recent_count="${recent_count:-0}"
        emit INFO "最近 1 小时慢查询条数: ${recent_count}"

        if [ "${recent_count}" -ge "${SLOW_PER_HOUR_CRITICAL}" ] 2>/dev/null; then
            emit CRITICAL "最近1小时慢查询 ${recent_count} 条 超过橙色阈值 ${SLOW_PER_HOUR_CRITICAL}"
        elif [ "${recent_count}" -ge "${SLOW_PER_HOUR_WARN}" ] 2>/dev/null; then
            emit WARN "最近1小时慢查询 ${recent_count} 条 超过黄色阈值 ${SLOW_PER_HOUR_WARN}"
        fi
    else
        emit INFO "当前系统不支持 date -d，跳过近1小时慢查询统计（仅看总量）"
    fi

    # 慢查询日志文件大小
    local slow_size
    slow_size="$(docker exec "${DB_CONTAINER}" du -h "${SLOW_LOG_PATH}" 2>/dev/null | cut -f1)"
    emit INFO "慢查询日志大小: ${slow_size:-未知}"
}

# ============================================
# 检查 3：磁盘空间
# ============================================
check_disk() {
    emit INFO "========== 检查 3：磁盘空间 =========="
    # MySQL 数据目录所在分区的使用率
    local df_out
    df_out="$(docker exec "${DB_CONTAINER}" df -P /var/lib/mysql 2>/dev/null | tail -1)"
    if [ -n "${df_out}" ]; then
        # 格式：Filesystem 1024-blocks Used Available Capacity Mounted-on
        local fs total used avail pct mount
        fs="$(echo "${df_out}" | awk '{print $1}')"
        total="$(echo "${df_out}" | awk '{print $2}')"
        used="$(echo "${df_out}" | awk '{print $3}')"
        pct="$(echo "${df_out}" | awk '{print $5}' | tr -d '%')"
        mount="$(echo "${df_out}" | awk '{print $6}')"
        local total_gb used_gb
        total_gb="$(awk "BEGIN{printf \"%.1f\", ${total}/1024/1024}")"
        used_gb="$(awk "BEGIN{printf \"%.1f\", ${used}/1024/1024}")"
        emit INFO "数据分区 ${mount}（${fs}）：已用 ${used_gb}G / ${total_gb}G（${pct}%）"

        if [ "${pct}" -ge "${DISK_CRITICAL_PCT}" ] 2>/dev/null; then
            emit CRITICAL "数据分区使用率 ${pct}% 超过橙色阈值 ${DISK_CRITICAL_PCT}%"
        elif [ "${pct}" -ge "${DISK_WARN_PCT}" ] 2>/dev/null; then
            emit WARN "数据分区使用率 ${pct}% 超过黄色阈值 ${DISK_WARN_PCT}%"
        fi
    else
        emit WARN "无法获取数据目录磁盘信息"
    fi
}

# ============================================
# 检查 4：连接数
# ============================================
check_connections() {
    emit INFO "========== 检查 4：连接数 =========="
    local conn_info
    conn_info="$(run_sql "
        SELECT
            (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME='Threads_connected'),
            (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_VARIABLES WHERE VARIABLE_NAME='max_connections');
    ")" || { emit WARN "查询连接数失败"; return; }

    if [ -z "${conn_info}" ]; then
        # MariaDB 10.8 可能用 SHOW STATUS，回退方案
        conn_info="$(run_sql "SHOW GLOBAL STATUS LIKE 'Threads_connected';" 2>/dev/null | awk '{print $2}')"
        local max_conn
        max_conn="$(run_sql "SHOW GLOBAL VARIABLES LIKE 'max_connections';" 2>/dev/null | awk '{print $2}')"
        conn_info="${conn_info}	${max_conn}"
    fi

    local current max pct
    current="$(echo "${conn_info}" | awk '{print $1}')"
    max="$(echo "${conn_info}" | awk '{print $2}')"
    current="${current:-0}"
    max="${max:-1}"
    pct="$(awk "BEGIN{printf \"%d\", ${current}*100/${max}}")"
    emit INFO "当前连接 ${current} / 最大 ${max}（${pct}%）"

    if [ "${pct}" -ge "${CONN_CRITICAL_PCT}" ] 2>/dev/null; then
        emit CRITICAL "连接数使用率 ${pct}% 超过橙色阈值 ${CONN_CRITICAL_PCT}%"
    elif [ "${pct}" -ge "${CONN_WARN_PCT}" ] 2>/dev/null; then
        emit WARN "连接数使用率 ${pct}% 超过黄色阈值 ${CONN_WARN_PCT}%"
    fi
}

# ============================================
# 摘要
# ============================================
summary() {
    emit INFO "========== 监控摘要 =========="
    emit INFO "告警：WARN=${WARN_COUNT}  CRITICAL=${CRITICAL_COUNT}"
    if [ "${CRITICAL_COUNT}" -gt 0 ]; then
        emit CRITICAL "存在 ${CRITICAL_COUNT} 项橙色告警，请立即处理"
        exit 2
    elif [ "${WARN_COUNT}" -gt 0 ]; then
        emit WARN "存在 ${WARN_COUNT} 项黄色告警，请关注"
        exit 1
    else
        emit INFO "所有检查项正常"
        exit 0
    fi
}

# ============================================
# 主流程
# ============================================
main() {
    [ "${1:-}" = "--warn-only" ] && WARN_ONLY=1

    load_env
    preflight

    emit INFO "########################################################"
    emit INFO "# 数据库监控告警  容器: ${DB_CONTAINER}  库: ${DB_NAME}"
    emit INFO "########################################################"

    check_table_sizes
    check_slow_queries
    check_disk
    check_connections

    summary
}

main "$@"
