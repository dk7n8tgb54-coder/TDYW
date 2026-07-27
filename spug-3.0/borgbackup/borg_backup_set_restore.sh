#!/usr/bin/env bash
# ================================================================================
# TDYW BorgBackup 一致性恢复入口
# --------------------------------------------------------------------------------
# 从 borg archive 恢复 DB + documents/media。与 borg_backup_set_create.sh 配套。
# 默认值与备份脚本完全一致（容器名/volume 名/路径/borg.env 位置）。
#
# 三种模式：
#   无 --mode      只校验：borg check + borg list + 打印恢复计划，不改数据
#   --mode drill   隔离演练：容器名须含 test，文件恢复到 /tmp，DB 恢复到 tdyw_restore 库
#   --mode production 生产恢复：停 app → 恢复 DB（DROP+CREATE+导入）→ 替换 documents/media → 启 app
#
# 恢复原理：
#   - DB：borg extract --stdout <dump成员> | gunzip | mariadb（流式，不落地大文件）
#   - 文件：borg extract 到临时根 → rsync --delete 替换 volume mountpoint（中途失败不污染原数据）
#   - 失败时 app 保持停止，不自动启动不一致系统（与 backup_set_restore 一致）
#
# 用法：
#   1. 只校验
#      ./borgbackup/borg_backup_set_restore.sh tdyw-20260727-030000
#
#   2. 隔离演练
#      APP_CONTAINER=tdyw-test DB_CONTAINER=tdyw-db-test \
#      RESTORE_CLIENT_CNF=/opt/docker/borgbackup/restore-test.cnf \
#      ./borgbackup/borg_backup_set_restore.sh --mode drill tdyw-20260727-030000
#
#   3. 生产恢复
#      RESTORE_CLIENT_CNF=/opt/docker/borgbackup/tdyw_restore.cnf \
#      ./borgbackup/borg_backup_set_restore.sh --mode production tdyw-20260727-030000
#
# 主要环境变量（默认值与备份脚本一致）：
#   APP_CONTAINER       应用容器，默认 tdyw
#   DB_CONTAINER        数据库容器，默认 tdyw-db
#   DOCUMENTS_VOLUME    documents docker volume 名，默认 docker_tdyw-documents
#   MEDIA_VOLUME        media docker volume 名，默认 docker_tdyw-media
#   BORG_ENV_FILE       borg 配置文件（0600），含 BORG_REPO / BORG_PASSPHRASE
#   RESTORE_CLIENT_CNF  恢复用 MariaDB cnf（需 DROP/CREATE/导入权限），默认 tdyw_restore.cnf
#   RESTORE_DB          drill 时目标库名，默认 tdyw_restore
#   DRILL_ROOT          drill 时文件恢复根目录，默认 /tmp/tdyw-restore-drill
#   ASSUME_YES          YES 时跳过 production 确认提示
#   APP_STOP_TIMEOUT    停止应用最大等待秒数，默认 900
#   HEALTH_TIMEOUT      启动后健康检查最大等待秒数，默认 180
#   LOCK_FILE           全局锁，默认 /data/backups/tdyw/.backup.lock（与备份共享）
# ================================================================================

set -Eeuo pipefail
umask 027

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_CONTAINER="${APP_CONTAINER:-tdyw}"
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
DOCUMENTS_VOLUME="${DOCUMENTS_VOLUME:-docker_tdyw-documents}"
MEDIA_VOLUME="${MEDIA_VOLUME:-docker_tdyw-media}"

BORG_ENV_FILE="${BORG_ENV_FILE:-/opt/docker/borgbackup/borg.env}"
BORG_REPO="${BORG_REPO:-}"
BORG_PASSPHRASE="${BORG_PASSPHRASE:-}"

RESTORE_CLIENT_CNF="${RESTORE_CLIENT_CNF:-/opt/docker/borgbackup/tdyw_restore.cnf}"
RESTORE_DB="${RESTORE_DB:-tdyw_restore}"
DRILL_ROOT="${DRILL_ROOT:-/tmp/tdyw-restore-drill}"
ASSUME_YES="${ASSUME_YES:-NO}"
APP_STOP_TIMEOUT="${APP_STOP_TIMEOUT:-900}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
LOCK_FILE="${LOCK_FILE:-/data/backups/tdyw/.backup.lock}"

ARCHIVE=""
RESTORE_MODE=""
RUNTIME_DIR=""
APP_STOPPED_BY_SCRIPT=0
DB_RESULT="NOT RUN"
DOCUMENTS_RESULT="NOT RUN"
MEDIA_RESULT="NOT RUN"
CURRENT_STAGE="init"

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ERROR: $*" >&2; return 1; }
is_yes() { case "${1^^}" in YES|TRUE|1) return 0 ;; *) return 1 ;; esac; }
container_running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]; }

usage() {
    sed -n '3,45p' "${BASH_SOURCE[0]}"
}

# ============================================
# 参数解析
# ============================================
parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --mode)
                [ "$#" -ge 2 ] || { log "ERROR: --mode requires drill or production" >&2; exit 2; }
                RESTORE_MODE="$2"; shift 2 ;;
            --mode=*) RESTORE_MODE="${1#--mode=}"; shift ;;
            -h|--help) usage; exit 0 ;;
            --) shift; break ;;
            -*) log "ERROR: unknown argument: $1" >&2; exit 2 ;;
            *)
                [ -z "${ARCHIVE}" ] || { log "ERROR: only one archive may be selected" >&2; exit 2; }
                ARCHIVE="$1"; shift ;;
        esac
    done
    case "${RESTORE_MODE}" in ""|drill|production) ;; *) log "ERROR: --mode must be drill or production" >&2; exit 2 ;; esac
    [ -n "${ARCHIVE}" ] || { log "ERROR: archive name required" >&2; exit 2; }
}

# ============================================
# 加载 borg 配置 + 解析 volume
# ============================================
load_borg_env() {
    [ -f "${BORG_ENV_FILE}" ] || fail "borg env file missing: ${BORG_ENV_FILE}"
    local mode; mode="$(stat -c '%a' "${BORG_ENV_FILE}" 2>/dev/null || true)"
    case "${mode}" in 600|400) ;; *) fail "borg.env must have mode 0600 or 0400" ;; esac
    # shellcheck disable=SC1090
    set -a; . "${BORG_ENV_FILE}"; set +a
    [ -n "${BORG_REPO:-}" ] || fail "BORG_REPO is empty in ${BORG_ENV_FILE}"
    [ -n "${BORG_PASSPHRASE:-}" ] || fail "BORG_PASSPHRASE is empty (encrypted repo requires passphrase)"
    export BORG_REPO BORG_PASSPHRASE
}

resolve_volumes() {
    DOCS_MP="$(docker volume inspect -f '{{.Mountpoint}}' "${DOCUMENTS_VOLUME}" 2>/dev/null || true)"
    MED_MP="$(docker volume inspect -f '{{.Mountpoint}}' "${MEDIA_VOLUME}" 2>/dev/null || true)"
    [ -n "${DOCS_MP}" ] && [ -d "${DOCS_MP}" ] || fail "documents volume mountpoint not found: ${DOCUMENTS_VOLUME}"
    [ -n "${MED_MP}" ] && [ -d "${MED_MP}" ] || fail "media volume mountpoint not found: ${MEDIA_VOLUME}"
}

# ============================================
# 确认 archive 存在 + 定位 archive 内成员路径
# ============================================
resolve_archive() {
    load_borg_env
    log "Looking up archive ${ARCHIVE} in ${BORG_REPO}"
    borg list --short "${BORG_REPO}" | grep -qx "${ARCHIVE}" \
        || fail "archive not found: ${ARCHIVE} (borg list ${BORG_REPO} to see available)"
}

# archive 内 dump 成员路径（形如 /tmp/tdyw-borg.XXXXXX/database.sql.gz）
find_dump_member() {
    borg list --short "${BORG_REPO}::${ARCHIVE}" | grep -E 'database\.sql\.gz$' | head -1
}

# archive 内 manifest 成员路径
find_manifest_member() {
    borg list --short "${BORG_REPO}::${ARCHIVE}" | grep -E 'manifest\.json$' | head -1
}

# 从 manifest 读 source database_name（production 恢复目标库名）
extract_source_db_name() {
    local manifest_member db_name
    manifest_member="$(find_manifest_member || true)"
    if [ -n "${manifest_member}" ]; then
        db_name="$(borg extract --stdout "${BORG_REPO}::${ARCHIVE}" "${manifest_member}" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("database_name",""))' 2>/dev/null || true)"
        [ -n "${db_name}" ] && { printf '%s' "${db_name}"; return; }
    fi
    # fallback：从 DB 容器读 MYSQL_DATABASE
    docker exec "${DB_CONTAINER}" sh -c 'printf %s "${MYSQL_DATABASE:-}"' 2>/dev/null || true
}

# ============================================
# 全局锁
# ============================================
acquire_maintenance_lock() {
    command -v flock >/dev/null || fail "flock is required"
    mkdir -p -- "$(dirname "${LOCK_FILE}")"
    exec 9>"${LOCK_FILE}"
    flock -n 9 || fail "another backup or restore operation is already running"
}

# ============================================
# 只校验模式
# ============================================
verify_only() {
    CURRENT_STAGE="verify"
    log "Verifying archive ${ARCHIVE}"
    borg check --repository-only "${BORG_REPO}"
    log "Archive contents (first 40 entries):"
    borg list "${BORG_REPO}::${ARCHIVE}" | sed -n '1,40p'
    log "Archive info:"
    borg info "${BORG_REPO}::${ARCHIVE}" | grep -E 'Archive name|Time|Command line|Deduplicated|Number of files' || true
    log "Verification completed; no data was changed"
}

# ============================================
# 模式校验
# ============================================
apply_mode() {
    CURRENT_STAGE="apply_mode"
    case "${RESTORE_MODE}" in
        drill)
            [[ "${APP_CONTAINER}" == *test* && "${DB_CONTAINER}" == *test* ]] || \
                fail "drill mode requires 'test' in both container names (APP_CONTAINER=${APP_CONTAINER} DB_CONTAINER=${DB_CONTAINER})"
            [[ "${DRILL_ROOT}" == /tmp/* ]] || fail "drill mode requires DRILL_ROOT under /tmp"
            ;;
        production) ;;
    esac
}

print_plan() {
    echo "============================================================"
    echo " BorgBackup restore plan"
    echo "============================================================"
    echo "  archive:           ${ARCHIVE}"
    echo "  borg repo:         ${BORG_REPO}"
    echo "  execution mode:    ${RESTORE_MODE:-verify-only}"
    echo "  app container:     ${APP_CONTAINER}"
    echo "  db container:      ${DB_CONTAINER}"
    if [ -n "${RESTORE_MODE}" ]; then
        local target_db="${RESTORE_DB}"
        [ "${RESTORE_MODE}" = production ] && target_db="$(extract_source_db_name || echo '<unknown>')"
        echo "  database target:   ${target_db}"
        if [ "${RESTORE_MODE}" = drill ]; then
            echo "  files target:      ${DRILL_ROOT} (isolated)"
        else
            echo "  documents target:  ${DOCS_MP}"
            echo "  media target:      ${MED_MP}"
        fi
    fi
    echo "============================================================"
}

# ============================================
# production 确认
# ============================================
confirm_production() {
    [ "${RESTORE_MODE}" = production ] || return 0
    is_yes "${ASSUME_YES}" && return 0
    local target_db; target_db="$(extract_source_db_name || echo '<unknown>')"
    echo "WARNING: This will OVERWRITE database '${target_db}', documents and media from archive ${ARCHIVE}."
    printf 'Type RESTORE_PRODUCTION to continue: '
    local answer; read -r answer
    [ "${answer}" = "RESTORE_PRODUCTION" ] || { log "Restore cancelled"; exit 2; }
}

# ============================================
# 停止/恢复应用
# ============================================
stop_application() {
    CURRENT_STAGE="stop_application"
    if container_running "${APP_CONTAINER}"; then
        log "Stopping ${APP_CONTAINER}"
        docker stop -t "${APP_STOP_TIMEOUT}" "${APP_CONTAINER}" >/dev/null
        APP_STOPPED_BY_SCRIPT=1
    fi
    container_running "${APP_CONTAINER}" && fail "application container did not stop"
}

wait_for_app_health() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT)) running health
    while [ "$SECONDS" -lt "$deadline" ]; do
        running="$(docker inspect -f '{{.State.Running}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        if [ "${running}" = "true" ] && { [ "${health}" = "healthy" ] || [ "${health}" = "none" ]; }; then
            log "Application health check passed (health=${health})"
            return 0
        fi
        sleep 3
    done
    fail "application did not become healthy within ${HEALTH_TIMEOUT}s"
}

# ============================================
# DB 逻辑恢复（流式：borg extract --stdout | gunzip | mariadb）
# ============================================
restore_database_logical() {
    CURRENT_STAGE="restore_database"
    local dump_member target_db container_cnf client_bin dump_bin
    dump_member="$(find_dump_member)"
    [ -n "${dump_member}" ] || fail "database.sql.gz not found in archive ${ARCHIVE}"

    if [ "${RESTORE_MODE}" = production ]; then
        target_db="$(extract_source_db_name)"
        [ -n "${target_db}" ] || fail "could not determine source database name from manifest"
    else
        target_db="${RESTORE_DB}"
    fi
    log "Restoring database to '${target_db}'"

    # 校验恢复 cnf
    [ -f "${RESTORE_CLIENT_CNF}" ] && [ -r "${RESTORE_CLIENT_CNF}" ] || fail "restore cnf missing/unreadable: ${RESTORE_CLIENT_CNF}"
    local cnf_mode; cnf_mode="$(stat -c '%a' "${RESTORE_CLIENT_CNF}" 2>/dev/null || true)"
    case "${cnf_mode}" in 600|400) ;; *) fail "restore cnf must have mode 0600 or 0400" ;; esac

    # cnf 复制到 DB 容器
    container_cnf="/tmp/tdyw_restore_$$.cnf"
    docker cp "${RESTORE_CLIENT_CNF}" "${DB_CONTAINER}:${container_cnf}" >/dev/null
    docker exec "${DB_CONTAINER}" chmod 600 "${container_cnf}"

    client_bin="$(docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb || command -v mysql')"
    [ -n "${client_bin}" ] || fail "mariadb/mysql client unavailable in ${DB_CONTAINER}"

    # DROP + CREATE 目标库
    log "DROP DATABASE IF EXISTS ${target_db}; CREATE DATABASE ${target_db};"
    docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${container_cnf}" \
        --host=127.0.0.1 --port=3306 \
        -e "DROP DATABASE IF EXISTS \`${target_db}\`; CREATE DATABASE \`${target_db}\` DEFAULT CHARACTER SET utf8mb4;" \
        || { docker exec "${DB_CONTAINER}" rm -f "${container_cnf}" >/dev/null 2>&1 || true; fail "DROP/CREATE database failed"; }

    # 流式 extract → gunzip → 导入（不落地大文件）
    log "Streaming dump from archive → gunzip → mariadb ${target_db}"
    if ! borg extract --stdout "${BORG_REPO}::${ARCHIVE}" "${dump_member}" \
        | gunzip \
        | docker exec -i "${DB_CONTAINER}" "${client_bin}" \
            --defaults-extra-file="${container_cnf}" \
            --host=127.0.0.1 --port=3306 "${target_db}"; then
        docker exec "${DB_CONTAINER}" rm -f "${container_cnf}" >/dev/null 2>&1 || true
        fail "database import failed"
    fi
    # 校验：目标库表数量（在删 cnf 前校验，校验需要凭据访问 DB）
    local table_count
    table_count="$(docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${container_cnf}" \
        --host=127.0.0.1 --port=3306 --batch --skip-column-names \
        -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${target_db}'" 2>/dev/null || echo 0)"
    docker exec "${DB_CONTAINER}" rm -f "${container_cnf}" >/dev/null 2>&1 || true
    log "Database restored: ${target_db} (${table_count} tables)"
    DB_RESULT="SUCCESS (${target_db}, ${table_count} tables)"
}

# ============================================
# 文件恢复（borg extract 到临时根 → rsync --delete 替换 mountpoint）
# ============================================
restore_fileset() {
    local name="$1" vol="$2" mp="$3"
    CURRENT_STAGE="restore_${name}"
    local extract_root
    extract_root="$(mktemp -d /tmp/tdyw-restore-${name}.XXXXXX)"

    log "Extracting ${name} from archive to ${extract_root}"
    # borg extract 在当前目录重建 archive 内的绝对路径树
    # archive 里 documents/media 存的是 volume mountpoint 绝对路径（如 /var/lib/docker/volumes/.../_data）
    ( cd "${extract_root}" && borg extract "${BORG_REPO}::${ARCHIVE}" "${mp}" )

    # 验证 extract 结果存在
    local extracted_path="${extract_root}${mp}"
    if [ ! -d "${extracted_path}" ]; then
        rm -rf -- "${extract_root}"
        fail "${name} not found in archive (expected ${mp})"
    fi

    if [ "${RESTORE_MODE}" = drill ]; then
        # drill：文件留在 extract_root，复制到 DRILL_ROOT 供检查
        mkdir -p "${DRILL_ROOT}"
        local drill_target="${DRILL_ROOT}/${name}"
        rm -rf -- "${drill_target}"
        mv "${extracted_path}" "${drill_target}"
        rm -rf -- "${extract_root}"
        log "${name} restored to drill location: ${drill_target}"
    else
        # production：rsync --delete 替换 mountpoint（原子性有限，失败保持 app 停止人工介入）
        log "Replacing ${name} volume content at ${mp}"
        rsync -a --delete "${extracted_path}/" "${mp}/"
        rm -rf -- "${extract_root}"
        log "${name} volume replaced: ${mp}"
    fi
    eval "${name^^}_RESULT=SUCCESS"
}

# ============================================
# 执行恢复
# ============================================
execute_restore() {
    CURRENT_STAGE="execute_restore"
    command -v docker >/dev/null || fail "docker is required"
    command -v rsync >/dev/null || fail "rsync is required"
    command -v borg >/dev/null || fail "borg is required"

    resolve_volumes
    apply_mode
    print_plan
    confirm_production

    if [ "${RESTORE_MODE}" = production ] || [ "${RESTORE_MODE}" = drill ]; then
        stop_application
        restore_database_logical
        restore_fileset documents "${DOCUMENTS_VOLUME}" "${DOCS_MP}"
        restore_fileset media "${MEDIA_VOLUME}" "${MED_MP}"
    fi

    # production 完成后启动 app + 健康检查
    if [ "${APP_STOPPED_BY_SCRIPT}" -eq 1 ] && [ "${RESTORE_MODE}" = production ]; then
        CURRENT_STAGE="restart_application"
        log "Starting application container ${APP_CONTAINER}"
        docker start "${APP_CONTAINER}" >/dev/null
        APP_STOPPED_BY_SCRIPT=0
        wait_for_app_health
    elif [ "${APP_STOPPED_BY_SCRIPT}" -eq 1 ]; then
        # drill：保持 app 停止（文件在 /tmp，启动会连到不一致状态）
        log "Drill completed; ${APP_CONTAINER} remains stopped (drill files are isolated under ${DRILL_ROOT})"
        APP_STOPPED_BY_SCRIPT=0
    fi

    log "Restore completed: database=${DB_RESULT}, documents=${DOCUMENTS_RESULT}, media=${MEDIA_RESULT}"
}

# ============================================
# cleanup
# ============================================
cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    set +e
    if [ "${rc}" -ne 0 ] && [ "${APP_STOPPED_BY_SCRIPT}" -eq 1 ]; then
        log "ERROR: restore failed; ${APP_CONTAINER} remains stopped for inspection"
        log "  stage: ${CURRENT_STAGE}"
        log "  do NOT start the app manually until DB + files are both verified"
    fi
    [ -n "${RUNTIME_DIR}" ] && [ -d "${RUNTIME_DIR}" ] && rm -rf -- "${RUNTIME_DIR}"
    exit "${rc}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ============================================
# 主流程
# ============================================
main() {
    parse_args "$@"
    resolve_archive
    acquire_maintenance_lock

    if [ -z "${RESTORE_MODE}" ]; then
        resolve_volumes
        print_plan
        verify_only
        exit 0
    fi

    execute_restore
}

main "$@"
