#!/bin/bash
# ================================================================================
# 总控恢复脚本：从 backup_set 恢复数据库 + documents/media 文件链
# --------------------------------------------------------------------------------
# schema-v4 读取 manifest.json 并校验完整增量链；旧备份集仍读取 backup_set.meta。
# 新格式按正确顺序恢复：
#   1. 打印恢复计划
#   2. 恢复数据库
#   3. 从全量基线依次回放 documents 和 media 增量
#   4. 输出恢复报告
#
# 安全机制：
#   - 推荐使用 --mode drill / --mode production，避免环境变量拼写错误
#   - 不传 --mode 时默认 dry-run，必须 FORCE_RESTORE=YES 才执行真实恢复
#   - status 不是 SUCCESS 时默认拒绝恢复（除非 FORCE_FAILED_SET=YES）
#   - 找不到数据库备份或 documents 全量备份时直接失败
#   - backup_set.meta 不存在时直接失败
#
# 推荐用法：
#   # 演练恢复：恢复数据库到 tdyw_restore，不覆盖生产 documents
#   ./backup_set_restore.sh --mode drill backup_set_20260704_203000
#
#   # 生产回滚：恢复生产数据库 + 同一备份集内的 documents
#   ./backup_set_restore.sh --mode production backup_set_20260704_203000
#
#   # 高级用法仍可用：不传 --mode 时，按下面环境变量执行
#
# 环境变量：
#   BACKUP_SET_DIR       备份集目录（与位置参数二选一）
#   FORCE_RESTORE        YES 才执行真实恢复，否则只 dry-run
#   FORCE_FAILED_SET     YES 允许恢复 status=FAILED 的备份集
#   APP_CONTAINER        应用容器名，默认 tdyw
#   DB_CONTAINER         数据库容器名，默认 tdyw-db
#   RESTORE_DB           dump 模式恢复目标库名，默认 tdyw_restore
#   DROP_EXISTING        dump 模式是否先 DROP 目标库，默认 NO
#   ALLOW_RESTORE_TO_PRODUCTION  dump 模式恢复到生产库名时必须 YES
#   FORCE_PHYSICAL_RESTORE  mariabackup 模式执行卷恢复时必须 YES
#   START_AFTER_RESTORE  mariabackup 模式恢复后是否启动容器，默认 NO
#   CLEAR_TARGET         documents 恢复时是否清空目标目录，默认 YES
#   RESTORE_DOCUMENTS    AUTO|YES|NO，默认 AUTO
#   ASSUME_YES           YES 时跳过 --mode production 的二次确认
# ================================================================================

set -euo pipefail
umask 027

# ============================================
# 配置区
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TDYW_BACKUP_ROOT="${TDYW_BACKUP_ROOT:-/data/backups/tdyw}"
BACKUP_SETS_DIR="${BACKUP_SETS_DIR:-${TDYW_BACKUP_ROOT}/backup_sets}"

# 参数解析
RESTORE_MODE=""
POSITIONAL_BACKUP_SET=""
SHOW_HELP="NO"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --mode)
            if [ "$#" -lt 2 ]; then
                echo "ERROR: --mode 需要参数：drill 或 production" >&2
                exit 2
            fi
            RESTORE_MODE="$2"
            shift 2
            ;;
        --mode=*)
            RESTORE_MODE="${1#--mode=}"
            shift
            ;;
        -h|--help)
            SHOW_HELP="YES"
            shift
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "ERROR: 未知参数: $1" >&2
            exit 2
            ;;
        *)
            if [ -n "${POSITIONAL_BACKUP_SET}" ]; then
                echo "ERROR: 只能指定一个备份集，重复参数: $1" >&2
                exit 2
            fi
            POSITIONAL_BACKUP_SET="$1"
            shift
            ;;
    esac
done

while [ "$#" -gt 0 ]; do
    if [ -n "${POSITIONAL_BACKUP_SET}" ]; then
        echo "ERROR: 只能指定一个备份集，重复参数: $1" >&2
        exit 2
    fi
    POSITIONAL_BACKUP_SET="$1"
    shift
done

case "${RESTORE_MODE}" in
    ""|drill|production) ;;
    *)
        echo "ERROR: --mode 只能是 drill 或 production，当前: ${RESTORE_MODE}" >&2
        exit 2
        ;;
esac

# 位置参数或环境变量指定备份集
BACKUP_SET_DIR="${BACKUP_SET_DIR:-${POSITIONAL_BACKUP_SET:-}}"

# 恢复控制
FORCE_RESTORE="${FORCE_RESTORE:-NO}"
FORCE_FAILED_SET="${FORCE_FAILED_SET:-NO}"

# 容器名
APP_CONTAINER="${APP_CONTAINER:-tdyw}"
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"

# 数据库恢复选项（dump 模式）
RESTORE_DB="${RESTORE_DB:-tdyw_restore}"
SOURCE_DB_NAME="${SOURCE_DB_NAME:-}"
DROP_EXISTING="${DROP_EXISTING:-NO}"
ALLOW_RESTORE_TO_PRODUCTION="${ALLOW_RESTORE_TO_PRODUCTION:-NO}"
RESTORE_CLIENT_CNF="${RESTORE_CLIENT_CNF:-/etc/tdyw-backup/tdyw_restore.cnf}"
DATABASE_RESTORE_MODE="${DATABASE_RESTORE_MODE:-logical}"

# mariabackup 恢复选项
FORCE_PHYSICAL_RESTORE="${FORCE_PHYSICAL_RESTORE:-NO}"
START_AFTER_RESTORE="${START_AFTER_RESTORE:-NO}"

# documents 恢复选项
CLEAR_TARGET="${CLEAR_TARGET:-YES}"
RESTORE_DOCUMENTS="${RESTORE_DOCUMENTS:-AUTO}"
RESTORE_MEDIA="${RESTORE_MEDIA:-AUTO}"
DOCUMENTS_PATH="${DOCUMENTS_PATH:-/data/spug/spug_api/storage/documents}"
MEDIA_PATH="${MEDIA_PATH:-/data/spug/spug_api/media}"
DRILL_ROOT="${DRILL_ROOT:-/tmp/tdyw-restore-drill}"

# 子脚本路径
DUMP_RESTORE_SCRIPT="${SCRIPT_DIR}/mariadump_restore.sh"
MARIABACKUP_RESTORE_SCRIPT="${SCRIPT_DIR}/mariabackup_prepare_restore.sh"
DOCUMENTS_RESTORE_SCRIPT="${SCRIPT_DIR}/documents_restore.sh"

# 运行时变量（由 load_meta 设置）
BACKUP_SET_ID=""
META_FILE=""
DB_MODE=""
DATABASE_BACKUP_FILE=""
DATABASE_BACKUP_DIR=""
DOCUMENTS_BACKUP_DIR=""
DOCUMENTS_INCREMENTAL_DIR=""
DOCUMENTS_FULL_BACKUP_FILE=""
DOCUMENTS_EMPTY_FULL_META=""
DOCUMENTS_MODE=""
DOCUMENTS_INCREMENTAL_COUNT=0
META_STATUS=""
META_APP_CONTAINER=""
META_DB_CONTAINER=""

# 恢复结果
DB_RESTORE_RESULT="SKIPPED"
DOCS_RESTORE_RESULT="SKIPPED"
MEDIA_RESTORE_RESULT="SKIPPED"
V4_RUNTIME_DIR=""
V4_PLAN_FILE=""
V4_BACKUP_ROOT=""
V4_PHYSICAL_BACKUP_FILE=""
V4_APP_IMAGE=""
V4_PRODUCTION_ACTIVE=0
V4_CHAIN=()

# ============================================
# 日志函数
# ============================================
log() {
    local msg="$1"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${ts}] ${msg}"
}
log_ok()   { log "[OK]   $1"; }
log_info() { log "[INFO] $1"; }
log_warn() { log "[WARN] $1"; }
log_err()  { log "[ERROR] $1"; }

# ============================================
# 用法
# ============================================
usage() {
    cat <<EOF
Usage:
  ./backup_set_restore.sh --mode drill <backup_set_id|backup_set_dir>
  ./backup_set_restore.sh --mode production <backup_set_id|backup_set_dir>
  BACKUP_SET_DIR=/path/to/backup_set ./backup_set_restore.sh

Recommended modes:
  --mode drill
      Restore database into tdyw_restore, drop/recreate tdyw_restore if needed,
      and never touch production documents. Use this for restore drills.

  --mode production
      Restore production database and production documents from the same
      backup_set. Requires typing RESTORE_PRODUCTION unless ASSUME_YES=YES.

Legacy options when --mode is omitted:
  FORCE_RESTORE=YES              Required to perform real restore (default: dry-run)
  FORCE_FAILED_SET=YES           Allow restoring a FAILED backup set
  APP_CONTAINER                  Default: tdyw
  DB_CONTAINER                   Default: tdyw-db

  # dump mode DB restore options
  RESTORE_CLIENT_CNF             0600/0400 client cnf; only credential source
  DATABASE_RESTORE_MODE          logical|physical, default: logical
  RESTORE_DB                     Default: tdyw_restore (NOT production)
  SOURCE_DB_NAME                 Production/source DB name, default: tdyw
  DROP_EXISTING=YES              Drop RESTORE_DB before import
  ALLOW_RESTORE_TO_PRODUCTION=YES  Required if RESTORE_DB equals source DB name

  # mariabackup mode DB restore options
  FORCE_PHYSICAL_RESTORE=YES     Required for destructive volume restore
  START_AFTER_RESTORE=YES        Start containers after restore

  # fileset restore options
  CLEAR_TARGET=YES               Default: YES. Clear target before restore.
  RESTORE_DOCUMENTS=AUTO|YES|NO  Default: AUTO. AUTO skips documents when
                                  dump restore targets a non-production DB.
  RESTORE_MEDIA=AUTO|YES|NO      Default: AUTO
  DRILL_ROOT                     Isolated fileset target, default /tmp/tdyw-restore-drill

Important:
  - Prefer --mode drill or --mode production to avoid variable typos.
  - Without --mode, default is dry-run. Set FORCE_RESTORE=YES to execute.
  - Schema-v4 restores verify the complete fileset chain and SHA256SUMS first.
  - Never restore database, documents, or media from different target dates.
EOF
}

apply_restore_mode() {
    case "${RESTORE_MODE}" in
        "")
            return 0
            ;;
        drill)
            FORCE_RESTORE="YES"
            DROP_EXISTING="YES"
            RESTORE_DOCUMENTS="NO"
            if [ "${DB_MODE}" = "dump" ]; then
                RESTORE_DB="tdyw_restore"
                ALLOW_RESTORE_TO_PRODUCTION="NO"
            fi
            if [ "${DB_MODE}" = "mariabackup" ]; then
                FORCE_PHYSICAL_RESTORE="NO"
            fi
            ;;
        production)
            FORCE_RESTORE="YES"
            RESTORE_DOCUMENTS="YES"
            if [ "${DB_MODE}" = "dump" ]; then
                RESTORE_DB="${SOURCE_DB_NAME}"
                DROP_EXISTING="YES"
                ALLOW_RESTORE_TO_PRODUCTION="YES"
            fi
            if [ "${DB_MODE}" = "mariabackup" ]; then
                FORCE_PHYSICAL_RESTORE="YES"
            fi
            ;;
    esac
}

confirm_production_restore() {
    if [ "${RESTORE_MODE}" != "production" ]; then
        return 0
    fi

    if [ "${ASSUME_YES:-NO}" = "YES" ]; then
        log_warn "ASSUME_YES=YES，跳过生产恢复二次确认"
        return 0
    fi

    echo ""
    echo "============================================================"
    echo " 生产恢复二次确认"
    echo "============================================================"
    echo "  backup_set_id: ${BACKUP_SET_ID}"
    echo "  target DB:     ${RESTORE_DB}"
    echo "  documents:     production documents will be cleared/restored"
    echo "  media:         production media will be cleared/restored"
    echo ""
    echo "这会覆盖生产数据库、documents 和 media，请确认已进入维护窗口。"
    echo "============================================================"
    printf '请输入 RESTORE_PRODUCTION 继续: '
    local answer
    read -r answer
    if [ "${answer}" != "RESTORE_PRODUCTION" ]; then
        log_warn "用户取消生产恢复"
        exit 2
    fi
}

# ============================================
# 解析备份集路径
# ============================================
resolve_backup_set_dir() {
    if [ -z "${BACKUP_SET_DIR}" ]; then
        usage
        exit 2
    fi

    # 如果传入的是 backup_set_id（不是路径），拼接完整路径
    if [ ! -d "${BACKUP_SET_DIR}" ]; then
        local candidate="${BACKUP_SETS_DIR}/${BACKUP_SET_DIR}"
        if [ -d "${candidate}" ]; then
            BACKUP_SET_DIR="${candidate}"
        else
            log_err "备份集目录不存在: ${BACKUP_SET_DIR}"
            log_err "也未在 ${BACKUP_SETS_DIR} 下找到同名备份集"
            exit 1
        fi
    fi

    # 规范化为绝对路径
    BACKUP_SET_DIR="$(cd "${BACKUP_SET_DIR}" && pwd)"
    META_FILE="${BACKUP_SET_DIR}/backup_set.meta"
    BACKUP_SET_ID="$(basename "${BACKUP_SET_DIR}")"
}

# ============================================
# 读取 meta 值
# ============================================
get_meta() {
    local key="$1"
    grep "^${key}=" "${META_FILE}" 2>/dev/null | head -1 | cut -d'=' -f2-
}

trim_env_value() {
    local value="$1"
    value="${value%$'\r'}"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    printf '%s' "${value}"
}

load_source_db_name() {
    local env_file="${PROJECT_ROOT}/docker/.env"
    if [ ! -f "${env_file}" ]; then
        SOURCE_DB_NAME="${SOURCE_DB_NAME:-tdyw}"
        return 0
    fi

    local line key value
    while IFS= read -r line || [ -n "${line}" ]; do
        line="${line%$'\r'}"
        case "${line}" in
            ''|\#*) continue ;;
        esac
        key="${line%%=*}"
        value="${line#*=}"
        key="$(printf '%s' "${key}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        value="$(trim_env_value "${value}")"
        case "${key}" in
            MYSQL_DATABASE)
                if [ -n "${value}" ]; then
                    SOURCE_DB_NAME="${SOURCE_DB_NAME:-${value}}"
                fi
                ;;
        esac
    done < "${env_file}"
    SOURCE_DB_NAME="${SOURCE_DB_NAME:-tdyw}"
}

# backup_set.meta stores absolute paths for auditability. If a backup set was
# created on another host or before the production path change, rebase those
# paths to the selected BACKUP_SET_DIR so the set stays portable.
rebase_backup_set_path() {
    local value="$1"

    if [ -z "${value}" ]; then
        printf ''
        return 0
    fi

    if [ -e "${value}" ]; then
        printf '%s' "${value}"
        return 0
    fi

    case "${value}" in
        */database.sql.gz)
            printf '%s/database.sql.gz' "${BACKUP_SET_DIR}"
            ;;
        */database_physical.tar.gz)
            printf '%s/database_physical.tar.gz' "${BACKUP_SET_DIR}"
            ;;
        */documents_full.tar.gz)
            printf '%s/documents_full.tar.gz' "${BACKUP_SET_DIR}"
            ;;
        */database)
            printf '%s/database' "${BACKUP_SET_DIR}"
            ;;
        */documents)
            printf '%s/documents' "${BACKUP_SET_DIR}"
            ;;
        */database/*)
            printf '%s/database/%s' "${BACKUP_SET_DIR}" "$(basename "${value}")"
            ;;
        */documents/full/*)
            printf '%s/documents/full/%s' "${BACKUP_SET_DIR}" "$(basename "${value}")"
            ;;
        */documents/incremental/*)
            printf '%s/documents/incremental/%s' "${BACKUP_SET_DIR}" "$(basename "${value}")"
            ;;
        *)
            printf '%s' "${value}"
            ;;
    esac
}

# ============================================
# 加载并校验 backup_set.meta
# ============================================
load_meta() {
    if [ ! -f "${META_FILE}" ]; then
        log_err "backup_set.meta 不存在: ${META_FILE}"
        log_err "无法确认备份集的完整性与绑定关系，拒绝恢复"
        exit 1
    fi

    BACKUP_SET_ID="$(get_meta backup_set_id)"
    DB_MODE="$(get_meta db_mode)"
    DATABASE_BACKUP_FILE="$(get_meta database_backup_file)"
    DATABASE_BACKUP_DIR="$(get_meta database_backup_dir)"
    DOCUMENTS_BACKUP_DIR="$(get_meta documents_backup_dir)"
    DOCUMENTS_FULL_BACKUP_FILE="$(get_meta documents_full_backup_file)"
    DOCUMENTS_EMPTY_FULL_META=""
    DOCUMENTS_MODE="$(get_meta documents_mode)"
    DOCUMENTS_INCREMENTAL_COUNT="$(get_meta documents_incremental_count)"
    META_STATUS="$(get_meta status)"
    META_APP_CONTAINER="$(get_meta app_container)"
    META_DB_CONTAINER="$(get_meta db_container)"
    load_source_db_name

    DATABASE_BACKUP_DIR="$(rebase_backup_set_path "${DATABASE_BACKUP_DIR}")"
    DATABASE_BACKUP_FILE="$(rebase_backup_set_path "${DATABASE_BACKUP_FILE}")"
    DOCUMENTS_BACKUP_DIR="$(rebase_backup_set_path "${DOCUMENTS_BACKUP_DIR}")"
    DOCUMENTS_FULL_BACKUP_FILE="$(rebase_backup_set_path "${DOCUMENTS_FULL_BACKUP_FILE}")"

    # 如果 meta 中记录了容器名且当前环境变量是默认值，则用 meta 中的值
    if [ -n "${META_APP_CONTAINER}" ] && [ "${APP_CONTAINER}" = "tdyw" ]; then
        APP_CONTAINER="${META_APP_CONTAINER}"
    fi
    if [ -n "${META_DB_CONTAINER}" ] && [ "${DB_CONTAINER}" = "tdyw-db" ]; then
        DB_CONTAINER="${META_DB_CONTAINER}"
    fi

    log_ok "backup_set.meta 已加载"
    log_info "  backup_set_id:              ${BACKUP_SET_ID}"
    log_info "  status:                     ${META_STATUS}"
    log_info "  db_mode:                    ${DB_MODE}"
    log_info "  database_backup_file:       ${DATABASE_BACKUP_FILE}"
    log_info "  documents_full_backup_file: ${DOCUMENTS_FULL_BACKUP_FILE}"
    log_info "  documents_mode:             ${DOCUMENTS_MODE}"
    log_info "  documents_incremental_count: ${DOCUMENTS_INCREMENTAL_COUNT}"
}

# ============================================
# 校验备份集完整性
# ============================================
validate_backup_set() {
    log_info "校验备份集完整性..."

    # 1. status 校验
    if [ "${META_STATUS}" != "SUCCESS" ]; then
        if [ "${FORCE_FAILED_SET}" = "YES" ]; then
            log_warn "备份集 status=${META_STATUS}，已通过 FORCE_FAILED_SET=YES 强制恢复（风险自负）"
        else
            log_err "备份集 status=${META_STATUS}，不是 SUCCESS，拒绝恢复"
            log_err "如需强制恢复不完整的备份集，请设置 FORCE_FAILED_SET=YES（风险自负）"
            exit 1
        fi
    fi

    # 2. database 目录校验
    if [ -z "${DATABASE_BACKUP_DIR}" ] || [ ! -d "${DATABASE_BACKUP_DIR}" ]; then
        if [ -d "${BACKUP_SET_DIR}" ]; then
            log_warn "数据库备份目录不存在，回退到备份集根目录扫描: ${BACKUP_SET_DIR}"
            DATABASE_BACKUP_DIR="${BACKUP_SET_DIR}"
        else
            log_err "数据库备份目录不存在: ${DATABASE_BACKUP_DIR}"
            exit 1
        fi
    fi

    # 3. documents 目录校验
    if [ -z "${DOCUMENTS_BACKUP_DIR}" ] || [ ! -d "${DOCUMENTS_BACKUP_DIR}" ]; then
        if [ -d "${BACKUP_SET_DIR}" ]; then
            log_warn "documents 备份目录不存在，回退到备份集根目录扫描: ${BACKUP_SET_DIR}"
            DOCUMENTS_BACKUP_DIR="${BACKUP_SET_DIR}"
        else
            log_err "documents 备份目录不存在: ${DOCUMENTS_BACKUP_DIR}"
            exit 1
        fi
    fi

    # 4. 数据库备份文件校验
    # meta 中记录了文件名，但也可能为空（备份时未记录），回退到目录扫描
    if [ -z "${DATABASE_BACKUP_FILE}" ] || [ ! -f "${DATABASE_BACKUP_FILE}" ]; then
        log_warn "meta 中记录的数据库备份文件不存在或为空，尝试在目录中扫描..."
        case "${DB_MODE}" in
            dump)
                if [ -f "${BACKUP_SET_DIR}/database.sql.gz" ]; then
                    DATABASE_BACKUP_FILE="${BACKUP_SET_DIR}/database.sql.gz"
                else
                    DATABASE_BACKUP_FILE="$(find "${DATABASE_BACKUP_DIR}" "${BACKUP_SET_DIR}" -maxdepth 1 -type f -name '*.sql.gz' 2>/dev/null | sort -u | tail -1)"
                fi
                ;;
            mariabackup)
                if [ -f "${BACKUP_SET_DIR}/database_physical.tar.gz" ]; then
                    DATABASE_BACKUP_FILE="${BACKUP_SET_DIR}/database_physical.tar.gz"
                else
                    DATABASE_BACKUP_FILE="$(find "${DATABASE_BACKUP_DIR}" "${BACKUP_SET_DIR}" -maxdepth 1 -type f \( -name '*_physical_*.tar.gz' -o -name 'database_physical.tar.gz' \) 2>/dev/null | sort -u | tail -1)"
                fi
                ;;
            *)
                log_err "meta 中 db_mode 不合法: ${DB_MODE}"
                exit 1
                ;;
        esac
    fi

    if [ -z "${DATABASE_BACKUP_FILE}" ] || [ ! -f "${DATABASE_BACKUP_FILE}" ]; then
        log_err "找不到数据库备份文件，目录: ${DATABASE_BACKUP_DIR}"
        exit 1
    fi
    log_ok "数据库备份文件: ${DATABASE_BACKUP_FILE}"

    # 5. documents 全量备份文件校验
    if [ -z "${DOCUMENTS_FULL_BACKUP_FILE}" ] || [ ! -f "${DOCUMENTS_FULL_BACKUP_FILE}" ]; then
        log_warn "meta 中记录的 documents 全量备份文件不存在或为空，尝试在目录中扫描..."
        if [ -f "${BACKUP_SET_DIR}/documents_full.tar.gz" ]; then
            DOCUMENTS_FULL_BACKUP_FILE="${BACKUP_SET_DIR}/documents_full.tar.gz"
        elif [ -d "${DOCUMENTS_BACKUP_DIR}/full" ]; then
            DOCUMENTS_FULL_BACKUP_FILE="$(find "${DOCUMENTS_BACKUP_DIR}/full" -maxdepth 1 -type f -name 'documents_full_*.tar.gz' 2>/dev/null | sort | tail -1)"
        else
            DOCUMENTS_FULL_BACKUP_FILE="$(find "${DOCUMENTS_BACKUP_DIR}" "${BACKUP_SET_DIR}" -maxdepth 1 -type f \( -name 'documents_full.tar.gz' -o -name 'documents_full_*.tar.gz' \) 2>/dev/null | sort -u | tail -1)"
        fi
    fi

    if [ -z "${DOCUMENTS_FULL_BACKUP_FILE}" ] || [ ! -f "${DOCUMENTS_FULL_BACKUP_FILE}" ]; then
        local full_meta meta_file_count
        full_meta=""
        if [ -f "${BACKUP_SET_DIR}/documents_full.meta" ]; then
            full_meta="${BACKUP_SET_DIR}/documents_full.meta"
        elif [ -d "${DOCUMENTS_BACKUP_DIR}/full" ]; then
            full_meta="$(find "${DOCUMENTS_BACKUP_DIR}/full" -maxdepth 1 -type f -name 'documents_full_*.meta' 2>/dev/null | sort | tail -1)"
        else
            full_meta="$(find "${DOCUMENTS_BACKUP_DIR}" "${BACKUP_SET_DIR}" -maxdepth 1 -type f -name 'documents_full*.meta' 2>/dev/null | sort -u | tail -1)"
        fi
        meta_file_count="$(grep -E '^file_count=' "${full_meta}" 2>/dev/null | tail -1 | cut -d= -f2-)"

        if [ -n "${full_meta}" ] && [ "${meta_file_count}" = "0" ]; then
            DOCUMENTS_EMPTY_FULL_META="${full_meta}"
            log_warn "documents 全量备份记录为 0 个物理文件，仅存在 meta: ${DOCUMENTS_EMPTY_FULL_META}"
            log_warn "这是允许的：资料库空文件夹/父文件夹结构由数据库记录恢复，documents 卷无需空目录归档。"
        else
            log_err "找不到 documents 全量备份文件"
            log_err "  documents 目录: ${DOCUMENTS_BACKUP_DIR}"
            log_err "  全量备份是恢复的基础；若 documents 确实无物理文件，应存在 file_count=0 的 documents_full_*.meta"
            exit 1
        fi
    else
        log_ok "documents 全量备份文件: ${DOCUMENTS_FULL_BACKUP_FILE}"
    fi

    # 6. 校验归档完整性
    log_info "校验数据库备份归档..."
    case "${DATABASE_BACKUP_FILE}" in
        *.tar.gz)
            if ! tar tzf "${DATABASE_BACKUP_FILE}" >/dev/null 2>&1; then
                log_err "数据库备份 tar.gz 校验失败: ${DATABASE_BACKUP_FILE}"
                exit 1
            fi
            ;;
        *.gz)
            if ! gzip -t "${DATABASE_BACKUP_FILE}" 2>/dev/null; then
                log_err "数据库备份 gzip 校验失败: ${DATABASE_BACKUP_FILE}"
                exit 1
            fi
            ;;
    esac
    log_ok "数据库备份归档校验通过"

    if [ -n "${DOCUMENTS_FULL_BACKUP_FILE}" ] && [ -f "${DOCUMENTS_FULL_BACKUP_FILE}" ]; then
        log_info "校验 documents 全量备份归档..."
        if ! tar tzf "${DOCUMENTS_FULL_BACKUP_FILE}" >/dev/null 2>&1; then
            log_err "documents 全量备份 tar.gz 校验失败: ${DOCUMENTS_FULL_BACKUP_FILE}"
            exit 1
        fi
        log_ok "documents 全量备份归档校验通过"
    else
        log_warn "documents 无物理文件全量归档，跳过 tar.gz 校验"
    fi

    # 7. 校验增量备份归档
    if [ -d "${DOCUMENTS_BACKUP_DIR}/incremental" ]; then
        DOCUMENTS_INCREMENTAL_DIR="${DOCUMENTS_BACKUP_DIR}/incremental"
    else
        DOCUMENTS_INCREMENTAL_DIR="${DOCUMENTS_BACKUP_DIR}"
    fi
    local incr_dir="${DOCUMENTS_INCREMENTAL_DIR}"
    if [ -d "${incr_dir}" ]; then
        local incr_file
        while IFS= read -r incr_file; do
            [ -z "${incr_file}" ] && continue
            if ! tar tzf "${incr_file}" >/dev/null 2>&1; then
                log_err "documents 增量备份 tar.gz 校验失败: ${incr_file}"
                exit 1
            fi
        done < <(find "${incr_dir}" -maxdepth 1 -type f -name 'documents_incr_*.tar.gz' 2>/dev/null | sort)
        log_ok "documents 增量备份归档校验通过"
    fi

    log_ok "备份集完整性校验通过"
}

# ============================================
# 打印恢复计划
# ============================================
print_restore_plan() {
    echo ""
    echo "============================================================"
    echo " 备份集恢复计划"
    echo "============================================================"
    echo "  backup_set_id:           ${BACKUP_SET_ID}"
    echo "  backup_set_dir:          ${BACKUP_SET_DIR}"
    echo "  status:                  ${META_STATUS}"
    echo "  db_mode:                 ${DB_MODE}"
    echo "  restore_mode:            ${RESTORE_MODE:-legacy-env}"
    echo "  app_container:           ${APP_CONTAINER}"
    echo "  db_container:            ${DB_CONTAINER}"
    echo ""
    echo "  [数据库恢复]"
    case "${DB_MODE}" in
        dump)
            echo "  脚本:    mariadump_restore.sh"
            echo "  备份文件: ${DATABASE_BACKUP_FILE}"
            echo "  目标库:   ${RESTORE_DB}"
            echo "  源/生产库: ${SOURCE_DB_NAME}"
            echo "  DROP_EXISTING:                ${DROP_EXISTING}"
            echo "  ALLOW_RESTORE_TO_PRODUCTION:  ${ALLOW_RESTORE_TO_PRODUCTION}"
            ;;
        mariabackup)
            echo "  脚本:    mariabackup_prepare_restore.sh"
            echo "  备份文件: ${DATABASE_BACKUP_FILE}"
            echo "  FORCE_PHYSICAL_RESTORE:  ${FORCE_PHYSICAL_RESTORE}"
            echo "  START_AFTER_RESTORE:     ${START_AFTER_RESTORE}"
            ;;
    esac
    echo ""
    echo "  [documents 恢复]"
    echo "  脚本:       documents_restore.sh"
    echo "  全量备份:    ${DOCUMENTS_FULL_BACKUP_FILE}"
    echo "  增量目录:    ${DOCUMENTS_INCREMENTAL_DIR}"
    echo "  增量数量:    ${DOCUMENTS_INCREMENTAL_COUNT}"
    echo "  CLEAR_TARGET:                ${CLEAR_TARGET}"
    echo "  RESTORE_DOCUMENTS:           ${RESTORE_DOCUMENTS}"
    echo ""
    echo "  force_restore:           ${FORCE_RESTORE}"
    echo "============================================================"
    echo ""
    log_warn "恢复顺序：数据库 → documents"
    log_warn "恢复前请确保已停止业务写入（暂停资料库上传 / 进入维护窗口）"
    echo ""
}

# ============================================
# 恢复数据库
# ============================================
restore_database() {
    log_info "========== 恢复数据库 =========="

    case "${DB_MODE}" in
        dump)
            if [ ! -f "${DUMP_RESTORE_SCRIPT}" ]; then
                log_err "缺少脚本: ${DUMP_RESTORE_SCRIPT}"
                DB_RESTORE_RESULT="FAILED: script not found"
                return 1
            fi
            log_info "调用: mariadump_restore.sh  BACKUP_FILE=${DATABASE_BACKUP_FILE}"
            if BACKUP_FILE="${DATABASE_BACKUP_FILE}" \
               RESTORE_DB="${RESTORE_DB}" \
               SOURCE_DB_NAME="${SOURCE_DB_NAME}" \
               DROP_EXISTING="${DROP_EXISTING}" \
               ALLOW_RESTORE_TO_PRODUCTION="${ALLOW_RESTORE_TO_PRODUCTION}" \
               DB_CONTAINER="${DB_CONTAINER}" \
               bash "${DUMP_RESTORE_SCRIPT}"; then
                log_ok "数据库逻辑恢复完成（目标库: ${RESTORE_DB}）"
                DB_RESTORE_RESULT="SUCCESS (restored to ${RESTORE_DB})"
            else
                log_err "数据库逻辑恢复失败"
                DB_RESTORE_RESULT="FAILED"
                return 1
            fi
            ;;
        mariabackup)
            if [ ! -f "${MARIABACKUP_RESTORE_SCRIPT}" ]; then
                log_err "缺少脚本: ${MARIABACKUP_RESTORE_SCRIPT}"
                DB_RESTORE_RESULT="FAILED: script not found"
                return 1
            fi
            log_info "调用: mariabackup_prepare_restore.sh  PHYSICAL_BACKUP_FILE=${DATABASE_BACKUP_FILE}"
            log_warn "mariabackup 物理恢复会覆盖 /var/lib/mysql 数据卷，属于破坏性操作"
            if PHYSICAL_BACKUP_FILE="${DATABASE_BACKUP_FILE}" \
               FORCE_PHYSICAL_RESTORE="${FORCE_PHYSICAL_RESTORE}" \
               START_AFTER_RESTORE="${START_AFTER_RESTORE}" \
               DB_CONTAINER="${DB_CONTAINER}" \
               APP_CONTAINER="${APP_CONTAINER}" \
               bash "${MARIABACKUP_RESTORE_SCRIPT}"; then
                log_ok "数据库物理恢复完成"
                DB_RESTORE_RESULT="SUCCESS"
            else
                local rc=$?
                # mariabackup_prepare_restore.sh 在 prepare-only 模式（无 FORCE_PHYSICAL_RESTORE）时返回 2
                if [ "${rc}" -eq 2 ] && [ "${FORCE_PHYSICAL_RESTORE}" != "YES" ]; then
                    log_warn "mariabackup 仅完成 prepare（未执行卷恢复），需手动设置 FORCE_PHYSICAL_RESTORE=YES"
                    DB_RESTORE_RESULT="PREPARE ONLY (set FORCE_PHYSICAL_RESTORE=YES for volume restore)"
                else
                    log_err "数据库物理恢复失败"
                    DB_RESTORE_RESULT="FAILED"
                    return 1
                fi
            fi
            ;;
        *)
            log_err "未知的 db_mode: ${DB_MODE}"
            DB_RESTORE_RESULT="FAILED: unknown db_mode"
            return 1
            ;;
    esac

    return 0
}

# ============================================
# 恢复 documents
# ============================================
restore_documents() {
    log_info "========== 恢复 documents =========="

    if [ -n "${DOCUMENTS_EMPTY_FULL_META}" ] && [ -z "${DOCUMENTS_FULL_BACKUP_FILE}" ]; then
        log_warn "documents 备份集中没有物理文件需要恢复，仅处理目标目录清理。"
        log_warn "数据库恢复后，资料库空文件夹/父子关系由数据库记录提供。"

        if [ "${FORCE_RESTORE}" != "YES" ]; then
            log_warn "DRY-RUN：如需清空目标 documents 目录，请设置 FORCE_RESTORE=YES。"
            DOCS_RESTORE_RESULT="DRY-RUN (empty documents set)"
            return 0
        fi

        if [ "$(docker inspect -f '{{.State.Running}}' "${APP_CONTAINER}" 2>/dev/null || echo false)" != "true" ]; then
            log_err "容器 ${APP_CONTAINER} 未运行，无法清理 documents 目录"
            DOCS_RESTORE_RESULT="FAILED: app container not running"
            return 1
        fi

        local target_path
        target_path="$(grep -E '^documents_path=' "${DOCUMENTS_EMPTY_FULL_META}" 2>/dev/null | tail -1 | cut -d= -f2-)"
        target_path="${target_path:-/data/spug/spug_api/storage/documents}"

        if [ "${CLEAR_TARGET}" = "YES" ]; then
            log_info "清空目标 documents 目录: ${APP_CONTAINER}:${target_path}"
            docker exec "${APP_CONTAINER}" sh -c "find '${target_path}' -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +"
        else
            log_warn "CLEAR_TARGET=${CLEAR_TARGET}，跳过清空目标 documents 目录"
        fi

        DOCS_RESTORE_RESULT="SUCCESS (empty documents set)"
        return 0
    fi

    if [ ! -f "${DOCUMENTS_RESTORE_SCRIPT}" ]; then
        log_err "缺少脚本: ${DOCUMENTS_RESTORE_SCRIPT}"
        DOCS_RESTORE_RESULT="FAILED: script not found"
        return 1
    fi

    local incr_dir="${DOCUMENTS_INCREMENTAL_DIR:-${DOCUMENTS_BACKUP_DIR}}"
    log_info "调用: documents_restore.sh"
    log_info "  FULL_BACKUP_FILE=${DOCUMENTS_FULL_BACKUP_FILE}"
    log_info "  INCREMENTAL_DIR=${incr_dir}"
    log_info "  CLEAR_TARGET=${CLEAR_TARGET}"
    log_info "  FORCE_RESTORE=${FORCE_RESTORE}"

    if FULL_BACKUP_FILE="${DOCUMENTS_FULL_BACKUP_FILE}" \
       INCREMENTAL_DIR="${incr_dir}" \
       CLEAR_TARGET="${CLEAR_TARGET}" \
       FORCE_RESTORE="${FORCE_RESTORE}" \
       APP_CONTAINER="${APP_CONTAINER}" \
       bash "${DOCUMENTS_RESTORE_SCRIPT}"; then
        log_ok "documents 恢复完成"
        DOCS_RESTORE_RESULT="SUCCESS"
    else
        local rc=$?
        # documents_restore.sh 在 dry-run 模式返回 2
        if [ "${rc}" -eq 2 ] && [ "${FORCE_RESTORE}" != "YES" ]; then
            DOCS_RESTORE_RESULT="DRY-RUN (set FORCE_RESTORE=YES to execute)"
        else
            log_err "documents 恢复失败"
            DOCS_RESTORE_RESULT="FAILED"
            return 1
        fi
    fi

    return 0
}

should_restore_documents() {
    case "${RESTORE_DOCUMENTS}" in
        YES)
            return 0
            ;;
        NO)
            DOCS_RESTORE_RESULT="SKIPPED (RESTORE_DOCUMENTS=NO)"
            log_warn "RESTORE_DOCUMENTS=NO，跳过 documents 恢复"
            return 1
            ;;
        AUTO)
            ;;
        *)
            log_err "RESTORE_DOCUMENTS 不合法: ${RESTORE_DOCUMENTS}（可选: AUTO | YES | NO）"
            DOCS_RESTORE_RESULT="FAILED: invalid RESTORE_DOCUMENTS"
            return 2
            ;;
    esac

    if [ "${DB_MODE}" = "dump" ] && [ "${RESTORE_DB}" != "${SOURCE_DB_NAME}" ]; then
        DOCS_RESTORE_RESULT="SKIPPED (dump restored to non-production DB: ${RESTORE_DB})"
        log_warn "数据库逻辑备份已恢复到非生产库 ${RESTORE_DB}，跳过生产 documents 恢复"
        log_warn "原因：documents 目录服务于生产库 ${SOURCE_DB_NAME}；若只回滚物理文件会造成列表记录与文件不一致"
        log_warn "如确认要同时覆盖生产 documents，请显式设置 RESTORE_DOCUMENTS=YES"
        return 1
    fi

    if [ "${DB_MODE}" = "mariabackup" ] && [ "${FORCE_PHYSICAL_RESTORE}" != "YES" ]; then
        DOCS_RESTORE_RESULT="SKIPPED (database prepare only)"
        log_warn "mariabackup 当前仅 prepare，未覆盖数据库卷，跳过 documents 恢复"
        log_warn "如确认要覆盖生产 documents，请显式设置 RESTORE_DOCUMENTS=YES"
        return 1
    fi

    return 0
}

# ============================================
# 输出恢复报告
# ============================================
print_restore_report() {
    echo ""
    echo "============================================================"
    echo " 备份集恢复报告"
    echo "============================================================"
    echo "  backup_set_id:              ${BACKUP_SET_ID}"
    echo "  backup_set_dir:             ${BACKUP_SET_DIR}"
    echo "  db_mode:                    ${DB_MODE}"
    echo "  database restore result:    ${DB_RESTORE_RESULT}"
    echo "  documents restore result:   ${DOCS_RESTORE_RESULT}"
    echo "  documents full backup file: ${DOCUMENTS_FULL_BACKUP_FILE}"
    echo "  incremental backup count:   ${DOCUMENTS_INCREMENTAL_COUNT}"
    echo "  app_container:              ${APP_CONTAINER}"
    echo "  db_container:               ${DB_CONTAINER}"
    echo "============================================================"
    echo ""
    echo "  建议后续检查："
    echo "    1. 确认数据库表数量与记录数正常"
    echo "    2. 确认 documents 目录文件数与 manifest 一致"
    echo "    3. 前端抽查文件预览/下载功能"
    echo "    4. 检查应用日志无异常报错"
    echo "    5. 确认业务恢复正常后移除维护窗口"
    echo "============================================================"
}

# ============================================
# schema-v4 一致性备份集恢复
#
# 新格式不读取 backup_set.meta。validate_backup_chain.py 会先验证目标日期到全量基线的
# 每一个 SHA256SUMS、manifest、父链和数据库产物类型；任何缺口都会在写入前失败。
# ============================================
is_schema_v4_backup_set() {
    [ -f "${BACKUP_SET_DIR}/manifest.json" ] || return 1
    python3 - "${BACKUP_SET_DIR}/manifest.json" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
raise SystemExit(0 if payload.get("schema_version") == 4 else 1)
PY
}

v4_plan_get() {
    python3 - "${V4_PLAN_FILE}" "$1" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    value = json.load(handle)
for part in sys.argv[2].split("."):
    value = value[part]
if value is not None:
    print(value)
PY
}

wait_for_v4_app_health() {
    local timeout="${HEALTH_TIMEOUT:-180}" deadline=$((SECONDS + ${HEALTH_TIMEOUT:-180}))
    local running health
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        running="$(docker inspect -f '{{.State.Running}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        if [ "${running}" = "true" ] && { [ "${health}" = "healthy" ] || [ "${health}" = "none" ]; }; then
            log_ok "应用健康检查通过 (health=${health})"
            return 0
        fi
        sleep 3
    done
    log_err "应用在 ${timeout}s 内未恢复健康"
    return 1
}

v4_cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    set +e
    if [ "${V4_PRODUCTION_ACTIVE}" -eq 1 ]; then
        if [ "$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}" 2>/dev/null || true)" != "true" ]; then
            docker start "${DB_CONTAINER}" >/dev/null || rc=1
        fi
        if [ "$(docker inspect -f '{{.State.Running}}' "${APP_CONTAINER}" 2>/dev/null || true)" != "true" ]; then
            docker start "${APP_CONTAINER}" >/dev/null || rc=1
        fi
        wait_for_v4_app_health || rc=1
    fi
    if [ -n "${V4_RUNTIME_DIR}" ] && [ -d "${V4_RUNTIME_DIR}" ]; then
        rm -rf -- "${V4_RUNTIME_DIR}"
    fi
    exit "${rc}"
}

load_and_validate_v4_plan() {
    command -v python3 >/dev/null || { log_err "python3 is required"; exit 1; }
    command -v docker >/dev/null || { log_err "docker is required"; exit 1; }
    case "${DATABASE_RESTORE_MODE}" in
        logical|physical) ;;
        *) log_err "DATABASE_RESTORE_MODE 必须是 logical 或 physical"; exit 2 ;;
    esac
    V4_RUNTIME_DIR="$(mktemp -d /tmp/tdyw-restore-plan.XXXXXX)"
    V4_PLAN_FILE="${V4_RUNTIME_DIR}/restore-plan.json"
    python3 "${SCRIPT_DIR}/validate_backup_chain.py" \
        --backup-set-dir "${BACKUP_SET_DIR}" --output "${V4_PLAN_FILE}"
    BACKUP_SET_ID="$(v4_plan_get target_backup_set_id)"
    V4_BACKUP_ROOT="$(v4_plan_get backup_root)"
    SOURCE_DB_NAME="$(v4_plan_get source_database_name)"
    DATABASE_BACKUP_FILE="$(v4_plan_get logical_database_artifact)"
    V4_PHYSICAL_BACKUP_FILE="$(v4_plan_get physical_database_artifact)"
    mapfile -t V4_CHAIN < <(python3 - "${V4_PLAN_FILE}" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    for item in json.load(handle)["chain"]:
        print(item)
PY
    )
    [ "${#V4_CHAIN[@]}" -gt 0 ] || { log_err "恢复链为空"; exit 1; }
    if [ "${DATABASE_RESTORE_MODE}" = "physical" ]; then
        [ -n "${V4_PHYSICAL_BACKUP_FILE}" ] || {
            log_err "目标日期没有物理数据库产物；不能使用其他日期的物理备份代替"
            exit 1
        }
        DATABASE_BACKUP_FILE="${V4_PHYSICAL_BACKUP_FILE}"
        DB_MODE="mariabackup"
    else
        DB_MODE="dump"
    fi
    V4_APP_IMAGE="$(docker inspect -f '{{.Config.Image}}' "${APP_CONTAINER}" 2>/dev/null || true)"
    [ -n "${V4_APP_IMAGE}" ] || { log_err "无法确定应用镜像"; exit 1; }
    [ -f "${RESTORE_CLIENT_CNF}" ] || { log_err "恢复 client cnf 不存在: ${RESTORE_CLIENT_CNF}"; exit 1; }
    local cnf_mode
    cnf_mode="$(stat -c '%a' "${RESTORE_CLIENT_CNF}" 2>/dev/null || true)"
    case "${cnf_mode}" in 600|400) ;; *) log_err "恢复 client cnf 必须为 0600 或 0400"; exit 1 ;; esac
}

apply_v4_restore_mode() {
    case "${RESTORE_MODE}" in
        "")
            [ "${FORCE_RESTORE}" != "YES" ] || {
                log_err "schema-v4 真实恢复必须显式指定 --mode drill 或 --mode production"
                exit 2
            }
            ;;
        drill)
            [[ "${APP_CONTAINER}" == *test* && "${DB_CONTAINER}" == *test* ]] || {
                log_err "drill 模式要求 APP_CONTAINER 和 DB_CONTAINER 名称都包含 test"
                exit 2
            }
            [[ "${DRILL_ROOT}" == /tmp/* ]] || { log_err "drill 模式要求 DRILL_ROOT 位于 /tmp"; exit 2; }
            FORCE_RESTORE="YES"
            DROP_EXISTING="YES"
            RESTORE_DB="tdyw_restore"
            ALLOW_RESTORE_TO_PRODUCTION="NO"
            RESTORE_DOCUMENTS="YES"
            RESTORE_MEDIA="YES"
            if [ "${DATABASE_RESTORE_MODE}" = "physical" ]; then
                FORCE_PHYSICAL_RESTORE="YES"
            fi
            ;;
        production)
            FORCE_RESTORE="YES"
            DROP_EXISTING="YES"
            RESTORE_DB="${SOURCE_DB_NAME}"
            ALLOW_RESTORE_TO_PRODUCTION="YES"
            RESTORE_DOCUMENTS="YES"
            RESTORE_MEDIA="YES"
            if [ "${DATABASE_RESTORE_MODE}" = "physical" ]; then
                FORCE_PHYSICAL_RESTORE="YES"
            fi
            ;;
    esac
}

print_v4_restore_plan() {
    echo "============================================================"
    echo " schema-v4 一致性恢复计划"
    echo "============================================================"
    echo "  target backup_set:       ${BACKUP_SET_ID}"
    echo "  chain:                   ${V4_CHAIN[*]}"
    echo "  database restore mode:   ${DATABASE_RESTORE_MODE}"
    echo "  source database:         ${SOURCE_DB_NAME}"
    echo "  target database:         ${RESTORE_DB}"
    echo "  documents/media mode:    full baseline + ordered incrementals"
    if [ "${RESTORE_MODE}" = "drill" ]; then
        echo "  isolated files root:     ${DRILL_ROOT}"
    else
        echo "  documents target:        ${DOCUMENTS_PATH}"
        echo "  media target:            ${MEDIA_PATH}"
    fi
    echo "  execute:                  ${FORCE_RESTORE}"
    echo "============================================================"
}

restore_v4_database() {
    if [ "${DATABASE_RESTORE_MODE}" = "logical" ]; then
        BACKUP_FILE="${DATABASE_BACKUP_FILE}" \
        RESTORE_CLIENT_CNF="${RESTORE_CLIENT_CNF}" \
        RESTORE_DB="${RESTORE_DB}" SOURCE_DB_NAME="${SOURCE_DB_NAME}" \
        DROP_EXISTING="${DROP_EXISTING}" \
        ALLOW_RESTORE_TO_PRODUCTION="${ALLOW_RESTORE_TO_PRODUCTION}" \
        DB_CONTAINER="${DB_CONTAINER}" bash "${DUMP_RESTORE_SCRIPT}"
        DB_RESTORE_RESULT="SUCCESS (logical -> ${RESTORE_DB})"
        return 0
    fi

    local backup_image current_image
    backup_image="$(v4_plan_get database_image)"
    current_image="$(docker inspect -f '{{.Config.Image}}' "${DB_CONTAINER}")"
    if [ "${backup_image}" != "${current_image}" ] && [ "${ALLOW_PHYSICAL_IMAGE_MISMATCH:-NO}" != "YES" ]; then
        log_err "物理备份镜像不匹配: backup=${backup_image}, target=${current_image}"
        return 1
    fi
    PHYSICAL_BACKUP_FILE="${DATABASE_BACKUP_FILE}" \
    FORCE_PHYSICAL_RESTORE="${FORCE_PHYSICAL_RESTORE}" \
    START_AFTER_RESTORE=YES STOP_APP_CONTAINER=NO \
    DB_CONTAINER="${DB_CONTAINER}" APP_CONTAINER="${APP_CONTAINER}" \
    bash "${MARIABACKUP_RESTORE_SCRIPT}"
    DB_RESTORE_RESULT="SUCCESS (physical server-instance restore)"
}

restore_v4_fileset() {
    local name="$1" target_path="$2" result_var="$3"
    local -a common=(
        --backup-root /backup-root --chain "${V4_CHAIN[@]}"
        --fileset "${name}" --clear-target
    )
    if [ "${RESTORE_MODE}" = "drill" ]; then
        mkdir -p -- "${DRILL_ROOT}"
        docker run --rm --network none \
            -v "${SCRIPT_DIR}:/backup-code:ro" \
            -v "${V4_BACKUP_ROOT}:/backup-root:ro" \
            -v "${DRILL_ROOT}:/restore-output" \
            --entrypoint python3 "${V4_APP_IMAGE}" \
            /backup-code/restore_fileset_chain.py \
            "${common[@]}" --target "/restore-output/${name}"
    else
        docker run --rm --network none \
            --volumes-from "${APP_CONTAINER}" \
            -v "${SCRIPT_DIR}:/backup-code:ro" \
            -v "${V4_BACKUP_ROOT}:/backup-root:ro" \
            --entrypoint python3 "${V4_APP_IMAGE}" \
            /backup-code/restore_fileset_chain.py \
            "${common[@]}" --target "${target_path}"
    fi
    printf -v "${result_var}" '%s' "SUCCESS"
}

restore_schema_v4() {
    trap v4_cleanup EXIT INT TERM
    load_and_validate_v4_plan
    apply_v4_restore_mode
    print_v4_restore_plan
    if [ "${FORCE_RESTORE}" != "YES" ]; then
        log_info "DRY-RUN：完整校验已通过，未执行数据库或文件写入"
        trap - EXIT INT TERM
        rm -rf -- "${V4_RUNTIME_DIR}"
        V4_RUNTIME_DIR=""
        return 0
    fi
    confirm_production_restore

    if [ "${RESTORE_MODE}" = "production" ]; then
        V4_PRODUCTION_ACTIVE=1
        log_info "停止应用容器以冻结恢复期间的业务写入"
        docker stop -t "${APP_STOP_TIMEOUT:-900}" "${APP_CONTAINER}" >/dev/null
    fi

    restore_v4_database
    restore_v4_fileset documents "${DOCUMENTS_PATH}" DOCS_RESTORE_RESULT
    restore_v4_fileset media "${MEDIA_PATH}" MEDIA_RESTORE_RESULT

    if [ "${RESTORE_MODE}" = "production" ]; then
        docker start "${APP_CONTAINER}" >/dev/null
        wait_for_v4_app_health
        V4_PRODUCTION_ACTIVE=0
    fi
    log_ok "schema-v4 恢复完成"
    log_info "database=${DB_RESTORE_RESULT}, documents=${DOCS_RESTORE_RESULT}, media=${MEDIA_RESTORE_RESULT}"
    trap - EXIT INT TERM
    rm -rf -- "${V4_RUNTIME_DIR}"
    V4_RUNTIME_DIR=""
}

# ============================================
# 主流程
# ============================================
main() {
    if [ "${SHOW_HELP}" = "YES" ]; then
        usage
        exit 0
    fi

    resolve_backup_set_dir
    if is_schema_v4_backup_set; then
        restore_schema_v4
        return 0
    fi
    load_meta
    apply_restore_mode
    validate_backup_set
    print_restore_plan
    confirm_production_restore

    if [ "${FORCE_RESTORE}" != "YES" ]; then
        log_info "DRY-RUN 模式：仅打印恢复计划，不执行真实恢复。"
        log_info "如需执行真实恢复，推荐使用："
        log_info "  ./backup_set_restore.sh --mode drill ${BACKUP_SET_ID}"
        log_info "  ./backup_set_restore.sh --mode production ${BACKUP_SET_ID}"
        log_info ""
        log_warn "dump 模式恢复注意事项："
        log_warn "  - 默认恢复到 ${RESTORE_DB} 库（非生产库），需手动切换或验证后 rename"
        log_warn "  - 如需直接恢复到生产库，设置 RESTORE_DB=<生产库名> + ALLOW_RESTORE_TO_PRODUCTION=YES"
        log_warn "  - RESTORE_DOCUMENTS=AUTO 时，dump 恢复到非生产库会跳过生产 documents，避免库和物理文件不一致"
        log_warn "mariabackup 模式恢复注意事项："
        log_warn "  - 需额外设置 FORCE_PHYSICAL_RESTORE=YES 执行卷恢复"
        log_warn "  - 物理恢复会停止并覆盖数据库容器数据卷"
        exit 2
    fi

    local rc=0

    # 1. 恢复数据库
    if ! restore_database; then
        rc=1
        log_err "数据库恢复失败，中止后续恢复"
    fi

    # 2. 恢复 documents（仅在数据库恢复成功或 prepare-only 后执行）
    if [ "${rc}" -eq 0 ]; then
        if should_restore_documents; then
            if ! restore_documents; then
                rc=1
                log_err "documents 恢复失败"
            fi
        else
            doc_decision_rc=$?
            if [ "${doc_decision_rc}" -eq 2 ]; then
                rc=1
            fi
        fi
    else
        log_warn "数据库恢复失败，跳过 documents 恢复"
        DOCS_RESTORE_RESULT="SKIPPED (database restore failed)"
    fi

    # 3. 输出报告
    print_restore_report

    if [ "${rc}" -ne 0 ]; then
        log_err "恢复未完全成功，请检查上述报告并排查日志"
    else
        log_ok "恢复完成，请执行建议的一致性检查"
    fi

    exit "${rc}"
}

main "$@"
