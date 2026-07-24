#!/bin/bash
# ================================================================================
# MariaDB 物理热备份脚本（mariabackup）
# --------------------------------------------------------------------------------
# 第二阶段：非 root 化改造
#   - 不再从 docker/.env 读取 MYSQL_ROOT_PASSWORD
#   - 不再使用 --password=PASSWORD 传密码（进程参数可见）
#   - 改为支持 tdyw_backup 客户端配置文件（--defaults-extra-file）
#
# 凭据读取优先级：
#   1. BACKUP_CLIENT_CNF 环境变量（指向 0600 权限的 .cnf 文件）
#   2. docker/secrets/tdyw_backup.cnf（默认位置）
#   3. 旧版 docker/.env 的 MYSQL_BACKUP_PASSWORD（过渡兼容，打印警告）
#
# 特点：直接复制数据文件，不锁表（热备份），恢复快；文件大（接近原数据大小），
#       不可跨版本迁移。适合大数据库和生产环境的全量备份。
#
# 前置要求：容器内需安装 mariabackup，检查命令：
#   docker exec tdyw-db which mariabackup
# 若未安装（Ubuntu/Debian 基础镜像）：
#   docker exec tdyw-db apt-get update && docker exec tdyw-db apt-get install -y mariadb-backup
#
# 当前正式用法：
#   由 backup_set_create.sh 在持有全局锁、冻结业务写入并建立 .inprogress 目录后调用。
#   本脚本不应加入 cron，也不应作为独立生产备份入口。
#
# 内部 worker 接口（仅供 backup_set_create.sh）：
#   BACKUP_ORCHESTRATED=YES \
#   DB_CONTAINER=tdyw-db \
#   CONTAINER_CNF=/tmp/tdyw_backup_xxx.cnf \
#   PHYSICAL_OUTPUT_FILE=/path/to/backup_set.inprogress/database.mariabackup.tar.gz \
#   PHYSICAL_LOG_FILE=/path/to/backup_set.inprogress/database-physical.stderr.log \
#   ./mariabackup_backup.sh
#
# 旧版独立用法仅为兼容保留，必须显式设置 ALLOW_LEGACY_STANDALONE_BACKUP=YES：
#   ALLOW_LEGACY_STANDALONE_BACKUP=YES ./mariabackup_backup.sh
#
# 环境变量覆盖（可选）：
#   export BACKUP_DIR=/data/backups/mariadb/physical  # 备份输出目录
#   export LOG_FILE=/var/log/mariabackup.log           # 日志文件
#   export KEEP_DAYS=7                                  # 保留天数
#   export BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf  # 客户端配置文件
#   export DRY_RUN=YES                                 # 只打印命令不执行
# ================================================================================

set -euo pipefail
umask 077  # 物理备份包含完整数据库实例，只允许执行用户读写

# ============================================
# 统一 backup_set 内部 worker
#
# 该路径不读取宿主机密码、不管理保留策略、不启停应用，也不发布正式目录。client cnf
# 已由总入口安全复制到数据库容器。物理备份使用 mariabackup 获取一致副本，禁止直接
# 复制运行中的 /var/lib/mysql。
# ============================================
orchestrated_cleanup() {
    if [ -n "${ORCHESTRATED_TARGET_DIR:-}" ]; then
        case "${ORCHESTRATED_TARGET_DIR}" in
            /tmp/tdyw_mariabackup_worker_*)
                docker exec "${DB_CONTAINER}" rm -rf -- "${ORCHESTRATED_TARGET_DIR}" >/dev/null 2>&1 || true
                ;;
        esac
    fi
}

orchestrated_backup() {
    : "${DB_CONTAINER:?DB_CONTAINER is required}"
    : "${CONTAINER_CNF:?CONTAINER_CNF is required}"
    : "${PHYSICAL_OUTPUT_FILE:?PHYSICAL_OUTPUT_FILE is required}"
    : "${PHYSICAL_LOG_FILE:?PHYSICAL_LOG_FILE is required}"

    [ -d "$(dirname "${PHYSICAL_OUTPUT_FILE}")" ] || {
        echo "ERROR: physical output directory does not exist" >&2
        return 1
    }
    [ "$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}" 2>/dev/null || true)" = "true" ] || {
        echo "ERROR: database container is not running: ${DB_CONTAINER}" >&2
        return 1
    }
    docker exec "${DB_CONTAINER}" test -f "${CONTAINER_CNF}" || {
        echo "ERROR: container client cnf is missing" >&2
        return 1
    }
    docker exec "${DB_CONTAINER}" sh -c 'command -v mariabackup >/dev/null && command -v tar >/dev/null' || {
        echo "ERROR: mariabackup or tar is unavailable in database container" >&2
        return 1
    }

    local data_kb tmp_free_kb output_free_kb required_kb
    data_kb="$(docker exec "${DB_CONTAINER}" du -sk /var/lib/mysql | awk 'NR==1 {print $1}')"
    tmp_free_kb="$(docker exec "${DB_CONTAINER}" df -Pk /tmp | awk 'NR==2 {print $4}')"
    output_free_kb="$(df -Pk "$(dirname "${PHYSICAL_OUTPUT_FILE}")" | awk 'NR==2 {print $4}')"
    [[ "${data_kb}" =~ ^[0-9]+$ && "${tmp_free_kb}" =~ ^[0-9]+$ && "${output_free_kb}" =~ ^[0-9]+$ ]] || {
        echo "ERROR: unable to determine physical backup disk requirements" >&2
        return 1
    }
    required_kb=$(((data_kb * 110 + 99) / 100))
    [ "${tmp_free_kb}" -ge "${required_kb}" ] || {
        echo "ERROR: database container /tmp lacks space for mariabackup (required=${required_kb}KiB, free=${tmp_free_kb}KiB)" >&2
        return 1
    }
    [ "${output_free_kb}" -ge "${required_kb}" ] || {
        echo "ERROR: backup output filesystem lacks space for physical archive (required=${required_kb}KiB, free=${output_free_kb}KiB)" >&2
        return 1
    }

    ORCHESTRATED_TARGET_DIR="/tmp/tdyw_mariabackup_worker_$$"
    trap orchestrated_cleanup EXIT INT TERM
    : > "${PHYSICAL_LOG_FILE}"
    chmod 600 "${PHYSICAL_LOG_FILE}" "${PHYSICAL_OUTPUT_FILE}" 2>/dev/null || true

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting orchestrated mariabackup" >&2
    if ! docker exec "${DB_CONTAINER}" mariabackup \
            --defaults-extra-file="${CONTAINER_CNF}" \
            --backup --target-dir="${ORCHESTRATED_TARGET_DIR}" \
            >>"${PHYSICAL_LOG_FILE}" 2>&1; then
        echo "ERROR: mariabackup --backup failed" >&2
        return 1
    fi

    if ! docker exec "${DB_CONTAINER}" sh -c \
        'test -s "$1/xtrabackup_checkpoints" && grep -Eq "backup_type[[:space:]]*=[[:space:]]*full-backuped" "$1/xtrabackup_checkpoints"' \
        sh "${ORCHESTRATED_TARGET_DIR}"; then
        echo "ERROR: mariabackup completion marker is missing or invalid" >&2
        return 1
    fi

    if ! docker exec "${DB_CONTAINER}" tar czf - -C "${ORCHESTRATED_TARGET_DIR}" . \
        2>>"${PHYSICAL_LOG_FILE}" > "${PHYSICAL_OUTPUT_FILE}"; then
        echo "ERROR: physical backup archive creation failed" >&2
        return 1
    fi
    [ -s "${PHYSICAL_OUTPUT_FILE}" ] || {
        echo "ERROR: physical backup archive is empty" >&2
        return 1
    }
    tar -tzf "${PHYSICAL_OUTPUT_FILE}" ./xtrabackup_checkpoints >/dev/null || {
        echo "ERROR: physical backup archive does not contain xtrabackup_checkpoints" >&2
        return 1
    }
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Orchestrated mariabackup completed" >&2
}

if [ "${BACKUP_ORCHESTRATED:-NO}" = "YES" ]; then
    orchestrated_backup
    exit $?
fi

if [ "${ALLOW_LEGACY_STANDALONE_BACKUP:-NO}" != "YES" ]; then
    echo "ERROR: standalone physical backup is disabled; use backup_set_create.sh" >&2
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
DEFAULT_BACKUP_DIR="${TDYW_BACKUP_ROOT}/mariadb/physical"
DEFAULT_LOG_FILE="${TDYW_LOG_DIR}/mariabackup.log"
BACKUP_DIR="${BACKUP_DIR:-${DEFAULT_BACKUP_DIR}}"
LOG_FILE="${LOG_FILE:-${DEFAULT_LOG_FILE}}"

# Docker 配置
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"

# 数据库配置
DB_NAME="${DB_NAME:-tdyw}"
DB_USER="${DB_USER:-tdyw_backup}"
BACKUP_CLIENT_CNF="${BACKUP_CLIENT_CNF:-${PROJECT_ROOT}/docker/secrets/tdyw_backup.cnf}"
DEFAULT_ENV_FILE="${PROJECT_ROOT}/docker/.env"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
DB_PASSWORD=""

# 保留策略
KEEP_DAYS="${KEEP_DAYS:-7}"  # 物理备份文件大，少保留
SKIP_CLEANUP="${SKIP_CLEANUP:-NO}"
DRY_RUN="${DRY_RUN:-NO}"

# mariabackup 在容器内的临时目录
BACKUP_TMP_BASE="/tmp/mariabackup_tmp"

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
    if [ -f "${BACKUP_CLIENT_CNF}" ]; then
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

    # 过渡兼容
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

    CNF_TMPFILE=$(mktemp /tmp/mariabackup_cnf.XXXXXX.cnf)
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
        log_err "未找到 docker 命令"
        exit 1
    fi

    local state
    state="$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}" 2>/dev/null || echo "false")"
    if [ "${state}" != "true" ]; then
        log_err "容器 ${DB_CONTAINER} 未运行"
        exit 1
    fi
    log_ok "容器 ${DB_CONTAINER} 运行中"

    if ! docker exec "${DB_CONTAINER}" which mariabackup >/dev/null 2>&1; then
        log_err "容器内未安装 mariabackup"
        log_err "  docker exec ${DB_CONTAINER} apt-get update && docker exec ${DB_CONTAINER} apt-get install -y mariadb-backup"
        exit 1
    fi
    log_ok "mariabackup 已安装"

    mkdir -p "${BACKUP_DIR}"
    touch "${LOG_FILE}"
    log_ok "前置检查通过"
}

# ============================================
# mariabackup 物理热备份
# ============================================
backup_physical() {
    log_info "========== 开始 mariabackup 物理热备份 =========="

    local ts name target_dir out_file
    ts="$(date +"%Y%m%d_%H%M%S")"
    name="${DB_NAME}_physical_${ts}.tar.gz"
    target_dir="${BACKUP_TMP_BASE}_${ts}"
    out_file="${BACKUP_DIR}/${name}"

    log_info "目标文件: ${out_file}"
    log_info "容器内临时目录: ${target_dir}"
    # 不打印密码

    if [ "${DRY_RUN}" = "YES" ]; then
        log_info "[DRY_RUN] 将执行："
        log_info "  docker exec ${DB_CONTAINER} mariabackup --backup --defaults-extra-file=<CNF> --target-dir=${target_dir}"
        log_info "  docker exec ${DB_CONTAINER} tar czf - -C ${target_dir} . > ${out_file}"
        log_ok "[DRY_RUN] 完成（未实际执行）"
        return 0
    fi

    # 将 cnf 文件复制到容器内
    local container_cnf="/tmp/tdyw_backup_physical_$$.cnf"
    docker cp "${BACKUP_CLIENT_CNF}" "${DB_CONTAINER}:${container_cnf}" 2>/dev/null || {
        log_err "无法将客户端配置文件复制到容器"
        return 1
    }
    docker exec "${DB_CONTAINER}" chmod 600 "${container_cnf}" 2>/dev/null || true

    # 1) 在容器内执行 mariabackup（使用 --defaults-extra-file，不传 --password）
    log_info "执行 mariabackup --backup ..."
    if ! docker exec "${DB_CONTAINER}" \
            mariabackup --backup \
            --defaults-extra-file="${container_cnf}" \
            --target-dir="${target_dir}" \
            >>"${LOG_FILE}" 2>&1; then
        log_err "mariabackup 执行失败"
        docker exec "${DB_CONTAINER}" rm -f "${container_cnf}" 2>/dev/null || true
        docker exec "${DB_CONTAINER}" rm -rf "${target_dir}" 2>/dev/null || true
        return 1
    fi

    # 清理容器内 cnf 文件
    docker exec "${DB_CONTAINER}" rm -f "${container_cnf}" 2>/dev/null || true

    # 2) 校验备份完整性
    if ! docker exec "${DB_CONTAINER}" test -f "${target_dir}/xtrabackup_checkpoints"; then
        log_err "备份校验文件 xtrabackup_checkpoints 不存在"
        docker exec "${DB_CONTAINER}" rm -rf "${target_dir}" 2>/dev/null || true
        return 1
    fi
    log_ok "mariabackup 备份完整性校验通过"

    # 3) 打包
    log_info "打包并压缩备份文件..."
    if ! docker exec "${DB_CONTAINER}" \
            tar czf - -C "${target_dir}" . 2>>"${LOG_FILE}" > "${out_file}"; then
        log_err "打包失败"
        rm -f "${out_file}"
        docker exec "${DB_CONTAINER}" rm -rf "${target_dir}" 2>/dev/null || true
        return 1
    fi

    # 4) 清理容器内临时目录
    docker exec "${DB_CONTAINER}" rm -rf "${target_dir}" 2>/dev/null || true

    # 5) 校验输出文件
    if [ ! -s "${out_file}" ]; then
        log_err "物理备份文件为空"
        rm -f "${out_file}"
        return 1
    fi

    local size
    size="$(du -h "${out_file}" | cut -f1)"
    log_ok "物理备份完成: ${name} (${size})"

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
    local pattern="${DB_NAME}_physical_*.tar.gz"
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
    log_info "最近 5 个物理备份:"
    ls -lht "${BACKUP_DIR}"/${DB_NAME}_physical_*.tar.gz 2>/dev/null | head -5 | \
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
    log_info "# MariaDB 物理热备份任务开始（mariabackup）"
    log_info "# 容器: ${DB_CONTAINER}  数据库: ${DB_NAME}"
    log_info "########################################################"

    local rc=0
    backup_physical || rc=1

    summary

    if [ "${rc}" -ne 0 ]; then
        log_err "备份失败，请检查日志: ${LOG_FILE}"
    fi

    exit "${rc}"
}

main "$@"
