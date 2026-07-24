#!/bin/bash
# DEPRECATED：逻辑备份已由 backup_set_create.sh 在统一停写窗口内执行。
# 本脚本不得加入 cron；仅为读取历史独立备份流程而保留。
# ================================================================================
# MariaDB 逻辑备份脚本（mariadb-dump）
# --------------------------------------------------------------------------------
# 第二阶段：非 root 化改造
#   - 不再从 docker/.env 读取 MYSQL_ROOT_PASSWORD
#   - 不再使用 -pPASSWORD 传密码（进程参数可见）
#   - 改为支持 tdyw_backup 客户端配置文件（--defaults-extra-file）
#   - 数据库密码不通过命令行参数传入
#
# 凭据读取优先级：
#   1. BACKUP_CLIENT_CNF 环境变量（指向 0600 权限的 .cnf 文件）
#   2. docker/secrets/tdyw_backup.cnf（默认位置）
#   3. 旧版 docker/.env 的 MYSQL_BACKUP_PASSWORD（过渡兼容，打印警告）
#
# 特点：导出 SQL 文本，文件小（gzip 压缩），可跨版本/跨引擎迁移，可单库单表恢复
#
# 用法：
#   ./mariadump_backup.sh
#
# 环境变量覆盖（可选）：
#   export BACKUP_DIR=/data/backups/mariadb/dump   # 备份输出目录
#   export LOG_FILE=/var/log/mariadb_dump.log       # 日志文件
#   export KEEP_DAYS=30                              # 保留天数
#   export BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf  # 客户端配置文件
#   export DRY_RUN=YES                              # 只打印命令不执行
#   生产环境建议通过环境变量指定独立的绝对路径，避免备份与项目代码混在同一目录。
#
# 定时任务示例（crontab -e）：
#   0 2 * * *   BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf /path/to/mariadump_backup.sh >> /var/log/mariadb_dump_backup.log 2>&1
# ================================================================================

set -euo pipefail
umask 027  # 备份文件仅属主可读写（含敏感数据）

if [ "${ALLOW_LEGACY_STANDALONE_BACKUP:-NO}" != "YES" ]; then
    echo "ERROR: standalone database backup is disabled; use backup_set_create.sh" >&2
    exit 64
fi

# ============================================
# 配置区
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 备份目录与日志
TDYW_BACKUP_ROOT="${TDYW_BACKUP_ROOT:-/data/backups/tdyw}"
TDYW_LOG_DIR="${TDYW_LOG_DIR:-/var/log/tdyw-backup}"
DEFAULT_BACKUP_DIR="${TDYW_BACKUP_ROOT}/mariadb/dump"
DEFAULT_LOG_FILE="${TDYW_LOG_DIR}/mariadb_dump.log"
BACKUP_DIR="${BACKUP_DIR:-${DEFAULT_BACKUP_DIR}}"
LOG_FILE="${LOG_FILE:-${DEFAULT_LOG_FILE}}"

# Docker 配置（与 docker/docker-compose.yml 的 container_name 一致）
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"

# 数据库配置
DB_NAME="${DB_NAME:-tdyw}"
DB_USER="${DB_USER:-tdyw_backup}"
# 客户端配置文件路径（优先级：环境变量 > 默认位置）
BACKUP_CLIENT_CNF="${BACKUP_CLIENT_CNF:-${PROJECT_ROOT}/docker/secrets/tdyw_backup.cnf}"
# 过渡兼容：旧版从 docker/.env 读取密码（仅当 cnf 文件不存在时）
DEFAULT_ENV_FILE="${PROJECT_ROOT}/docker/.env"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
DB_PASSWORD=""  # 仅过渡兼容，不为空时打印警告

# 保留策略
KEEP_DAYS="${KEEP_DAYS:-30}"  # 逻辑备份文件小，保留久一点
SKIP_CLEANUP="${SKIP_CLEANUP:-NO}"
DRY_RUN="${DRY_RUN:-NO}"

# 临时文件（0600）
CNF_TMPFILE=""
TMPFILES=()

# ============================================
# 日志函数
# ============================================
log() {
    local msg="$1"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${ts}] ${msg}"
    echo "[${ts}] ${msg}" >> "${LOG_FILE}" 2>/dev/null || true
}
log_ok()   { log "[OK]   $1"; }
log_info() { log "[INFO] $1"; }
log_warn() { log "[WARN] $1"; }
log_err()  { log "[ERROR] $1"; }

# ============================================
# 清理临时文件
# ============================================
cleanup_tmpfiles() {
    for f in "${TMPFILES[@]:-}"; do
        [ -n "$f" ] && [ -f "$f" ] && rm -f "$f" 2>/dev/null || true
    done
}
trap cleanup_tmpfiles EXIT INT TERM

# ============================================
# 加载凭据
# ============================================
load_credentials() {
    # 优先使用客户端配置文件
    if [ -f "${BACKUP_CLIENT_CNF}" ]; then
        # 校验权限（仅 Linux）
        local perm
        perm=$(stat -c '%a' "${BACKUP_CLIENT_CNF}" 2>/dev/null || stat -f '%A' "${BACKUP_CLIENT_CNF}" 2>/dev/null | tr -d ' ')
        case "$perm" in
            600|640|400) : ;;
            *)
                log_err "客户端配置文件权限 ${perm} 过宽（要求 0600）: ${BACKUP_CLIENT_CNF}"
                exit 1
                ;;
        esac
        log_ok "使用客户端配置文件: ${BACKUP_CLIENT_CNF}"
        return 0
    fi

    # 过渡兼容：从 docker/.env 读取密码（打印安全警告）
    log_warn "未找到客户端配置文件 ${BACKUP_CLIENT_CNF}"
    log_warn "尝试从 ${ENV_FILE} 读取密码（过渡兼容，生产应使用 .cnf 文件）"

    if [ -f "${ENV_FILE}" ]; then
        while IFS='=' read -r key value || [ -n "${key}" ]; do
            key="${key%%#*}"
            key="$(echo "${key}" | xargs)"
            value="$(echo "${value}" | xargs)"
            [ -z "${key}" ] && continue
            case "${key}" in
                MYSQL_BACKUP_PASSWORD) DB_PASSWORD="${value}" ;;
                MYSQL_DATABASE)        DB_NAME="${value}" ;;
                MYSQL_PASSWORD)        [ -z "${DB_PASSWORD}" ] && DB_PASSWORD="${value}" ;;
            esac
        done < "${ENV_FILE}"
    fi

    if [ -z "${DB_PASSWORD}" ]; then
        log_err "未能获取备份账号密码。请创建客户端配置文件："
        log_err "  cp database_maintenance/db_accounts/backup_client.cnf.template ${BACKUP_CLIENT_CNF}"
        log_err "  # 填入 tdyw_backup 密码，chmod 0600"
        exit 1
    fi

    # 生成临时 cnf 文件（0600，避免密码进 argv）
    CNF_TMPFILE=$(mktemp /tmp/mariadb_backup.XXXXXX.cnf)
    chmod 600 "$CNF_TMPFILE"
    TMPFILES+=("$CNF_TMPFILE")
    cat > "$CNF_TMPFILE" <<EOF
[client]
user=${DB_USER}
password=${DB_PASSWORD}
EOF
    BACKUP_CLIENT_CNF="$CNF_TMPFILE"
    log_warn "使用临时凭据文件（过渡兼容），生产应使用固定 .cnf 文件"
}

# ============================================
# 前置检查
# ============================================
preflight() {
    log_info "前置检查..."

    if ! command -v docker >/dev/null 2>&1; then
        log_err "未找到 docker 命令，请确认 Docker 已安装"
        exit 1
    fi

    local state
    state="$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}" 2>/dev/null || echo "false")"
    if [ "${state}" != "true" ]; then
        log_err "容器 ${DB_CONTAINER} 未运行"
        exit 1
    fi
    log_ok "容器 ${DB_CONTAINER} 运行中"

    mkdir -p "${BACKUP_DIR}"
    touch "${LOG_FILE}"
    log_ok "前置检查通过"
}

# ============================================
# mariadb-dump 逻辑备份
# ============================================
backup_dump() {
    log_info "========== 开始 mariadb-dump 逻辑备份 =========="

    local ts name out_file
    ts="$(date +"%Y%m%d_%H%M%S")"
    name="${DB_NAME}_dump_${ts}.sql.gz"
    out_file="${BACKUP_DIR}/${name}"

    log_info "目标文件: ${out_file}"
    log_info "数据库: ${DB_NAME}  用户: ${DB_USER}"
    # 不打印密码

    # DRY_RUN 模式
    if [ "${DRY_RUN}" = "YES" ]; then
        log_info "[DRY_RUN] 将执行："
        log_info "  docker exec ${DB_CONTAINER} mariadb-dump --defaults-extra-file=<CNF> --single-transaction ... ${DB_NAME} | gzip > ${out_file}"
        log_ok "[DRY_RUN] 完成（未实际执行）"
        return 0
    fi

    # 将 cnf 文件复制到容器内（容器内无法直接访问宿主机文件）
    local container_cnf="/tmp/tdyw_backup_dump_$$.cnf"
    docker cp "${BACKUP_CLIENT_CNF}" "${DB_CONTAINER}:${container_cnf}" 2>/dev/null || {
        log_err "无法将客户端配置文件复制到容器"
        return 1
    }
    # 确保容器内文件权限
    docker exec "${DB_CONTAINER}" chmod 600 "${container_cnf}" 2>/dev/null || true

    # 执行 mariadb-dump（使用 --defaults-extra-file，不传 -p 密码）
    if ! docker exec "${DB_CONTAINER}" \
            mariadb-dump \
            --defaults-extra-file="${container_cnf}" \
            --single-transaction \
            --routines \
            --triggers \
            --events \
            --default-character-set=utf8mb4 \
            --set-charset \
            --quick \
            --hex-blob \
            "${DB_NAME}" 2>>"${LOG_FILE}" | gzip > "${out_file}"; then
        log_err "mariadb-dump 执行失败"
        rm -f "${out_file}"
        docker exec "${DB_CONTAINER}" rm -f "${container_cnf}" 2>/dev/null || true
        return 1
    fi

    # 清理容器内临时文件
    docker exec "${DB_CONTAINER}" rm -f "${container_cnf}" 2>/dev/null || true

    # 校验：备份文件不能为空
    if [ ! -s "${out_file}" ]; then
        log_err "备份文件为空，可能密码错误或数据库异常"
        rm -f "${out_file}"
        return 1
    fi

    # 校验 gzip 完整性
    if ! gzip -t "${out_file}" 2>/dev/null; then
        log_err "备份文件 gzip 校验失败，文件可能损坏"
        rm -f "${out_file}"
        return 1
    fi

    local size
    size="$(du -h "${out_file}" | cut -f1)"
    log_ok "逻辑备份完成: ${name} (${size})"

    if [ "${SKIP_CLEANUP}" = "YES" ]; then
        log_info "SKIP_CLEANUP=YES，跳过子脚本文件级清理"
    else
        cleanup "${KEEP_DAYS}"
    fi
}

# ============================================
# 清理过期备份
# ============================================
cleanup() {
    local days="$1"
    local pattern="${DB_NAME}_dump_*.sql.gz"
    local deleted
    deleted="$(find "${BACKUP_DIR}" -name "${pattern}" -type f -mtime +"${days}" -print -delete 2>/dev/null | wc -l)"
    if [ "${deleted}" -gt 0 ]; then
        log_ok "清理过期备份: 删除 ${deleted} 个文件（>${days} 天）"
    else
        log_info "无过期备份需清理（>${days} 天）"
    fi
}

# ============================================
# 备份完成摘要
# ============================================
summary() {
    log_info "========== 备份摘要 =========="
    log_info "备份目录: ${BACKUP_DIR}"
    log_info "最近 5 个逻辑备份:"
    ls -lht "${BACKUP_DIR}"/${DB_NAME}_dump_*.sql.gz 2>/dev/null | head -5 | \
        awk '{print "    " $9 " (" $5 ")"}' >> "${LOG_FILE}" 2>/dev/null || true
    log_info "日志文件: ${LOG_FILE}"
    log_info "磁盘占用:"
    du -sh "${BACKUP_DIR}" 2>/dev/null | awk '{print "    " $0}' >> "${LOG_FILE}" 2>/dev/null || true
    log_info "========== 备份完成 =========="
}

# ============================================
# 主流程
# ============================================
main() {
    mkdir -p "$(dirname "${LOG_FILE}")"

    load_credentials
    preflight

    log_info "########################################################"
    log_info "# MariaDB 逻辑备份任务开始（mariadb-dump）"
    log_info "# 容器: ${DB_CONTAINER}  数据库: ${DB_NAME}"
    log_info "########################################################"

    local rc=0
    backup_dump || rc=1

    summary

    if [ "${rc}" -ne 0 ]; then
        log_err "备份失败，请检查日志: ${LOG_FILE}"
    fi

    exit "${rc}"
}

main "$@"
