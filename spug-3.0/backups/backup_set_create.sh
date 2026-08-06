#!/usr/bin/env bash
# ================================================================================
# TDYW 统一一致性全量备份入口：MariaDB 逻辑全量 + documents/media 文件全量
# --------------------------------------------------------------------------------
# 适用环境：单机 Docker Compose，应用容器 tdyw，数据库容器 tdyw-db。
#
# 为什么必须使用本脚本：
#   数据库记录和附件文件必须来自同一个停止写入窗口。分别调度数据库和文件脚本会产生
#   “数据库有记录但文件缺失”或“文件存在但数据库无记录”的不一致状态。因此旧的
#   mariadump/documents/mariabackup 独立入口默认禁止正式执行。
#
# 一致性流程：
#   获取全局锁
#     -> 前置检查与磁盘检查
#     -> 停止 API 入口和 Celery beat
#     -> graceful stop 全部 Celery worker
#     -> 停止 tdyw 应用容器（tdyw-db 不停止）
#     -> 生成数据库逻辑全量；可选附加 mariabackup 物理全量
#     -> 生成 documents/media 独立文件全量
#     -> 生成 manifest.json 与 SHA256SUMS
#     -> 校验 gzip/tar/dump 结构/SHA-256
#     -> 启动 tdyw 并等待健康检查
#     -> 将 .inprogress 原子重命名为正式 backup_set
#
# 成功产物：
#   backup_set_YYYYmmdd_HHMMSS/
#     database.sql.gz                  # logical/both 模式
#     database.mariabackup.tar.gz      # physical/both 模式
#     documents.tar.gz
#     documents.manifest.json
#     media.tar.gz
#     media.manifest.json
#     manifest.json
#     SHA256SUMS
#
# 失败保护：
#   - 任一步失败、SIGINT 或 SIGTERM 都会通过 trap 尝试恢复 tdyw。
#   - 失败产物使用 .failed 后缀并写入 FAILED.json，不会伪装成完整备份。
#   - MariaDB 始终保持运行；物理备份只允许使用 mariabackup，禁止直接复制 /var/lib/mysql。
#   - 密码仅从 0600/0400 的 client cnf 读取，不进入 argv、manifest 或日志。
#
# 脚本用法（不接受备份类型位置参数，通过环境变量配置）：
#
#   1. 默认 dry-run：检查并验证 client cnf 登录，不停止服务、不创建或删除备份
#      BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf \
#      BACKUP_ROOT=/data/backups/tdyw/backup_sets \
#      ./backups/backup_set_create.sh
#
#   2. 正式一致性全量备份（推荐的每日调度方式）：数据库、documents 和 media
#      每次都生成可独立恢复的全量产物，不依赖任何父备份。
#      BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf \
#      BACKUP_ROOT=/data/backups/tdyw/backup_sets \
#      DRY_RUN=NO ./backups/backup_set_create.sh
#
#   3. 同时生成数据库逻辑全量和 mariabackup 物理全量
#      BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf \
#      BACKUP_ROOT=/data/backups/tdyw/backup_sets \
#      DB_BACKUP_MODE=both DRY_RUN=NO \
#      ./backups/backup_set_create.sh
#
#   4. 正式备份并清理超过 30 天的已验证成功全量备份   可选，确认恢复演练后再启用
#      BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf \
#      BACKUP_ROOT=/data/backups/tdyw/backup_sets \
#      DRY_RUN=NO RETENTION_DAYS=30 RETENTION_DELETE=YES \
#      ./backups/backup_set_create.sh
#
#   5. 隔离测试：容器名必须包含 test，输出目录必须位于 /tmp   仅测试环境使用
#      APP_CONTAINER=tdyw-test DB_CONTAINER=tdyw-db-test \
#      BACKUP_CLIENT_CNF=/tmp/tdyw-backup-test.cnf \
#      BACKUP_ROOT=/tmp/tdyw-backup-test/backup_sets \
#      TEST_MODE=YES DRY_RUN=NO ./backups/backup_set_create.sh
#
#   6. 查看帮助
#      ./backups/backup_set_create.sh --help
#
# 主要环境变量：
#   APP_CONTAINER       应用容器，默认 tdyw
#   DB_CONTAINER        数据库容器，默认 tdyw-db
#   DB_NAME             数据库名；未设置时从 DB 容器 MYSQL_DATABASE 读取
#   DB_BACKUP_MODE      logical|both，默认 logical；始终保留每日逻辑全量
#   FILESET_BACKUP_MODE 仅允许 full，默认 full；保留该变量用于显式拒绝旧增量配置
#   BACKUP_CLIENT_CNF   MariaDB client cnf；账号和密码仅从此文件读取
#   BACKUP_ROOT         backup_set 根目录，默认 /data/backups/tdyw/backup_sets
#   MIN_FREE_PERCENT    备份盘最低空闲百分比，默认 20
#   APP_STOP_TIMEOUT    停止应用最大等待秒数，默认 900
#   HEALTH_TIMEOUT      启动后健康检查最大等待秒数，默认 180
#   RETENTION_DAYS      本地保留天数，默认 30
#   RETENTION_DELETE    YES 时才删除通过完整校验的过期成功备份，默认 NO
#   TEST_MODE           YES 时强制使用名称含 test 的容器和 /tmp 下备份目录
# ================================================================================

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_CONTAINER="${APP_CONTAINER:-tdyw}"
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
DB_NAME="${DB_NAME:-}"
DB_BACKUP_MODE="${DB_BACKUP_MODE:-logical}"
FILESET_BACKUP_MODE="${FILESET_BACKUP_MODE:-full}"
BACKUP_CLIENT_CNF="${BACKUP_CLIENT_CNF:-/etc/tdyw-backup/tdyw_backup.cnf}"
BACKUP_ROOT="${BACKUP_ROOT:-/data/backups/tdyw/backup_sets}"
DOCUMENTS_PATH="${DOCUMENTS_PATH:-/data/spug/spug_api/storage/documents}"
MEDIA_PATH="${MEDIA_PATH:-/data/spug/spug_api/media}"
DRY_RUN="${DRY_RUN:-YES}"
TEST_MODE="${TEST_MODE:-NO}"
MIN_FREE_PERCENT="${MIN_FREE_PERCENT:-20}"
APP_STOP_TIMEOUT="${APP_STOP_TIMEOUT:-900}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
RETENTION_DELETE="${RETENTION_DELETE:-NO}"
PHYSICAL_BACKUP_WORKER="${PHYSICAL_BACKUP_WORKER:-${SCRIPT_DIR}/mariabackup_backup.sh}"

BACKUP_SET_ID="backup_set_$(date '+%Y%m%d_%H%M%S')"
TEMP_DIR=""
FINAL_DIR="${BACKUP_ROOT}/${BACKUP_SET_ID}"
FAILED_DIR="${BACKUP_ROOT}/${BACKUP_SET_ID}.failed"
RUNTIME_DIR=""
LOCK_FILE="${BACKUP_ROOT}/.backup.lock"
CONTAINER_CNF=""
APP_IMAGE=""
DB_IMAGE=""
DB_ACCOUNT=""
APP_STOPPED=0
APP_NEEDS_RESTART=0
CURRENT_STAGE="preflight"
STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
FREEZE_STARTED_EPOCH=0
FREEZE_SECONDS=0

# ============================================
# 通用日志、布尔值和参数校验
# ============================================
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ERROR: $*" >&2; return 1; }

usage() {
    cat <<'USAGE'
Usage: backup_set_create.sh [--help]

The script defaults to DRY_RUN=YES. Set DRY_RUN=NO explicitly for a real backup.
Every successful set contains a full logical database dump and independent full
documents/media archives. New incremental fileset backups are intentionally disabled.

Dry-run:
  BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf \
  BACKUP_ROOT=/data/backups/tdyw/backup_sets \
  ./backups/backup_set_create.sh

Recommended daily full backup:
  BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf \
  BACKUP_ROOT=/data/backups/tdyw/backup_sets \
  DRY_RUN=NO ./backups/backup_set_create.sh

Full backup with an additional physical MariaDB artifact:
  BACKUP_CLIENT_CNF=/etc/tdyw-backup/tdyw_backup.cnf \
  BACKUP_ROOT=/data/backups/tdyw/backup_sets \
  DB_BACKUP_MODE=both DRY_RUN=NO \
  ./backups/backup_set_create.sh

Isolated test:
  APP_CONTAINER=tdyw-test DB_CONTAINER=tdyw-db-test \
  BACKUP_CLIENT_CNF=/tmp/tdyw-backup-test.cnf \
  BACKUP_ROOT=/tmp/tdyw-backup-test/backup_sets \
  TEST_MODE=YES DRY_RUN=NO ./backups/backup_set_create.sh
USAGE
}

is_yes() {
    case "${1^^}" in YES|TRUE|1) return 0 ;; *) return 1 ;; esac
}

validate_number() {
    [[ "$2" =~ ^[0-9]+$ ]] || fail "$1 must be a non-negative integer"
}

container_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

# ============================================
# 应用恢复与健康检查
#
# APP_NEEDS_RESTART 只在脚本开始修改 Supervisor 后置 1，避免误启动未被本脚本修改的容器。
# docker start 成功后还必须等待 Compose healthcheck；仅进程 Running 不视为恢复成功。
# ============================================
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

restore_application() {
    if [ "${APP_NEEDS_RESTART}" -ne 1 ]; then
        return 0
    fi
    log "Restoring application container ${APP_CONTAINER}"
    if container_running "${APP_CONTAINER}"; then
        if ! docker restart -t "${APP_STOP_TIMEOUT}" "${APP_CONTAINER}" >/dev/null; then
            fail "failed to restart application container ${APP_CONTAINER}"
            return 1
        fi
    else
        if ! docker start "${APP_CONTAINER}" >/dev/null; then
            fail "failed to start application container ${APP_CONTAINER}"
            return 1
        fi
    fi
    APP_STOPPED=0
    APP_NEEDS_RESTART=0
    wait_for_app_health
}

# ============================================
# 失败状态与统一 trap
#
# failure_stage 只记录固定阶段名，不记录可能含密码、路径内容或连接串的原始异常文本。
# 临时 cnf 无论成功失败都从数据库容器删除。
# ============================================
write_failure_marker() {
    local rc="$1"
    [ -n "${TEMP_DIR}" ] && [ -d "${TEMP_DIR}" ] || return 0
    printf '{\n  "backup_set_id": "%s",\n  "status": "FAILED",\n  "failure_stage": "%s",\n  "exit_code": %s\n}\n' \
        "${BACKUP_SET_ID}" "${CURRENT_STAGE//[^a-zA-Z0-9_.-]/_}" "${rc}" > "${TEMP_DIR}/FAILED.json"
    if [ ! -e "${FAILED_DIR}" ]; then
        mv -- "${TEMP_DIR}" "${FAILED_DIR}" || true
        TEMP_DIR=""
        log "Failed backup retained for diagnosis: ${FAILED_DIR}"
    fi
}

cleanup() {
    local rc=$?
    local failure_stage="${CURRENT_STAGE}"
    trap - EXIT INT TERM
    set +e
    if [ "${APP_NEEDS_RESTART}" -eq 1 ]; then
        CURRENT_STAGE="restore_after_failure"
        if ! restore_application; then
            rc=1
            failure_stage="restore_after_failure"
        fi
    fi
    if [ -n "${CONTAINER_CNF}" ]; then
        docker exec "${DB_CONTAINER}" rm -f -- "${CONTAINER_CNF}" >/dev/null 2>&1 || true
    fi
    if [ "${rc}" -ne 0 ]; then
        CURRENT_STAGE="${failure_stage}"
        write_failure_marker "${rc}"
    fi
    if [ -n "${RUNTIME_DIR}" ] && [ -d "${RUNTIME_DIR}" ]; then
        rm -rf -- "${RUNTIME_DIR}"
    fi
    exit "${rc}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ============================================
# 前置检查
#
# 此阶段执行只读检查和一次 SELECT 权限验证，因此 DRY_RUN 也会执行。验证时 cnf 仅
# 临时复制到 DB 容器 /tmp 并立即删除。账号和密码由 MariaDB 客户端直接从 cnf 读取，
# 脚本不会使用环境变量或命令行参数覆盖。TEST_MODE 额外限制测试容器名和输出目录。
# ============================================
resolve_backup_modes() {
    case "${DB_BACKUP_MODE}" in
        logical|both) ;;
        *) fail "DB_BACKUP_MODE must be logical or both; daily logical backup is mandatory" ;;
    esac
    [ "${FILESET_BACKUP_MODE}" = "full" ] || \
        fail "FILESET_BACKUP_MODE only supports full; incremental backup generation is disabled"
}

preflight() {
    CURRENT_STAGE="preflight"
    command -v docker >/dev/null || fail "docker is required"
    command -v flock >/dev/null || fail "flock is required"
    command -v gzip >/dev/null || fail "gzip is required"
    command -v sha256sum >/dev/null || fail "sha256sum is required"
    command -v tar >/dev/null || fail "tar is required"
    command -v python3 >/dev/null || fail "python3 is required"

    validate_number MIN_FREE_PERCENT "${MIN_FREE_PERCENT}"
    validate_number APP_STOP_TIMEOUT "${APP_STOP_TIMEOUT}"
    validate_number HEALTH_TIMEOUT "${HEALTH_TIMEOUT}"
    validate_number RETENTION_DAYS "${RETENTION_DAYS}"
    resolve_backup_modes
    container_running "${APP_CONTAINER}" || fail "application container is not running: ${APP_CONTAINER}"
    container_running "${DB_CONTAINER}" || fail "database container is not running: ${DB_CONTAINER}"

    if [ -z "${DB_NAME}" ]; then
        DB_NAME="$(docker exec "${DB_CONTAINER}" sh -c 'printf %s "${MYSQL_DATABASE:-}"')"
    fi
    [ -n "${DB_NAME}" ] || fail "DB_NAME is empty and MYSQL_DATABASE is unavailable in ${DB_CONTAINER}"

    APP_IMAGE="$(docker inspect -f '{{.Config.Image}}' "${APP_CONTAINER}")"
    DB_IMAGE="$(docker inspect -f '{{.Config.Image}}' "${DB_CONTAINER}")"
    [ -n "${APP_IMAGE}" ] || fail "could not determine application image"
    [ -n "${DB_IMAGE}" ] || fail "could not determine database image"

    docker exec "${APP_CONTAINER}" test -d "${DOCUMENTS_PATH}" || fail "documents path is missing"
    docker exec "${APP_CONTAINER}" test -d "${MEDIA_PATH}" || fail "media path is missing"
    docker exec "${APP_CONTAINER}" supervisorctl status >/dev/null || fail "supervisorctl is unavailable in the application container"
    docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb-dump >/dev/null || command -v mysqldump >/dev/null' || \
        fail "mariadb-dump/mysqldump is unavailable in ${DB_CONTAINER}"
    if [ "${DB_BACKUP_MODE}" = "both" ]; then
        [ -f "${PHYSICAL_BACKUP_WORKER}" ] || fail "physical backup worker is missing: ${PHYSICAL_BACKUP_WORKER}"
        docker exec "${DB_CONTAINER}" sh -c 'command -v mariabackup >/dev/null' || \
            fail "mariabackup is unavailable in ${DB_CONTAINER}"
    fi
    docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb >/dev/null || command -v mysql >/dev/null' || \
        fail "mariadb/mysql client is unavailable in ${DB_CONTAINER}"

    [ -e "${BACKUP_CLIENT_CNF}" ] || fail "backup client cnf is missing"
    [ -f "${BACKUP_CLIENT_CNF}" ] || fail "backup client cnf is not a regular file"
    [ -r "${BACKUP_CLIENT_CNF}" ] || fail "backup client cnf is not readable by $(id -un)"
    ! grep -q 'REPLACE_WITH_' "${BACKUP_CLIENT_CNF}" || fail "backup client cnf still contains a template placeholder"
    local cnf_mode
    cnf_mode="$(stat -c '%a' "${BACKUP_CLIENT_CNF}" 2>/dev/null || true)"
    case "${cnf_mode}" in 600|400) ;; *) fail "backup client cnf must have mode 0600 or 0400" ;; esac
    validate_database_credentials

    if is_yes "${TEST_MODE}"; then
        [[ "${APP_CONTAINER}" == *test* && "${DB_CONTAINER}" == *test* ]] || \
            fail "TEST_MODE requires container names containing 'test'"
        [[ "${BACKUP_ROOT}" == /tmp/* ]] || fail "TEST_MODE requires BACKUP_ROOT below /tmp"
    fi
}

# ============================================
# 磁盘空间检查
#
# 当前按文件系统可用百分比做硬门槛。首次上线还需按手册人工确认可用字节数能够容纳
# DB dump、documents 和 media 各一份以及压缩过程开销。
# ============================================
check_disk_space() {
    CURRENT_STAGE="disk_space"
    local probe="${BACKUP_ROOT}" used_percent free_percent
    while [ ! -e "${probe}" ] && [ "${probe}" != "/" ]; do
        probe="$(dirname "${probe}")"
    done
    used_percent="$(df -P "${probe}" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
    [[ "${used_percent}" =~ ^[0-9]+$ ]] || fail "could not determine backup filesystem usage"
    free_percent=$((100 - used_percent))
    [ "${free_percent}" -ge "${MIN_FREE_PERCENT}" ] || \
        fail "backup filesystem has ${free_percent}% free; minimum is ${MIN_FREE_PERCENT}%"
    log "Disk check passed: ${free_percent}% free"
}

# ============================================
# 执行计划（不会打印密码或 cnf 内容）
#
# document_chunks 是未完成分片上传的临时状态；已提交文件已进入 documents，因此明确
# 排除。日志、Redis/预览缓存和临时文件也不属于权威业务数据。
# ============================================
print_plan() {
    cat <<PLAN
backup_set_id=${BACKUP_SET_ID}
application_container=${APP_CONTAINER}
database_container=${DB_CONTAINER}
database_name=${DB_NAME}
database_account=${DB_ACCOUNT}
database_backup_mode=${DB_BACKUP_MODE}
fileset_backup_mode=full
documents_path=${DOCUMENTS_PATH}
media_path=${MEDIA_PATH}
document_chunks=EXCLUDED_TRANSIENT_UPLOAD_STATE
backup_root=${BACKUP_ROOT}
dry_run=${DRY_RUN}
PLAN
}

# ============================================
# 全局维护锁和 .inprogress 工作目录
#
# 锁文件与 backup_set 位于同一备份根目录。正式目录、失败目录和临时目录重名时立即失败，
# 防止 mv 把新目录嵌套进已有目录。
# ============================================
acquire_maintenance_lock() {
    CURRENT_STAGE="lock"
    command -v flock >/dev/null || fail "flock is required"
    mkdir -p -- "${BACKUP_ROOT}"
    chmod 700 "${BACKUP_ROOT}"
    exec 9>"${LOCK_FILE}"
    flock -n 9 || fail "another backup or restore operation is already running"
}

initialize_backup_workdir() {
    TEMP_DIR="${BACKUP_ROOT}/${BACKUP_SET_ID}.inprogress"
    [ ! -e "${TEMP_DIR}" ] && [ ! -e "${FINAL_DIR}" ] && [ ! -e "${FAILED_DIR}" ] || \
        fail "backup set id already exists: ${BACKUP_SET_ID}"
    mkdir -p -- "${TEMP_DIR}"
    chmod 700 "${TEMP_DIR}"
    RUNTIME_DIR="$(mktemp -d /tmp/tdyw-backup-runtime.XXXXXX)"
}

# ============================================
# 停止入口、beat 和写 worker
#
# 顺序很重要：先关入口，阻止用户产生新任务；再关 beat，阻止定时任务；最后让全部
# Celery worker 完成当前任务并退出。无法证明只读的 worker 一律按写处理。
# Supervisor 的 stopwaitsecs 决定 graceful stop 上限，超时必须失败，不能继续备份。
# ============================================
stop_supervisor_programs() {
    local status_file="${RUNTIME_DIR}/supervisor.before" program
    docker exec "${APP_CONTAINER}" supervisorctl status > "${status_file}"
    # 从首次修改 Supervisor 状态起，任何失败都必须整体重启应用以恢复 autostart programs。
    APP_NEEDS_RESTART=1

    # Stop ingress first so no new HTTP/WebSocket work can be accepted.
    for program in nginx spug-api spug-api-upload spug-ws; do
        if awk -v name="${program}" '$1 == name && $2 == "RUNNING" {found=1} END {exit !found}' "${status_file}"; then
            log "Gracefully stopping ${program}"
            docker exec "${APP_CONTAINER}" supervisorctl stop "${program}" >/dev/null
        fi
    done

    # Beat must stop before workers, preventing new scheduled tasks.
    while IFS= read -r program; do
        [ -n "${program}" ] || continue
        log "Gracefully stopping ${program}"
        docker exec "${APP_CONTAINER}" supervisorctl stop "${program}" >/dev/null
    done < <(awk '$2 == "RUNNING" && $1 ~ /celery.*beat/ {print $1}' "${status_file}")

    # Every Celery worker is treated as a writer unless proven otherwise.
    while IFS= read -r program; do
        [ -n "${program}" ] || continue
        log "Gracefully draining ${program}"
        docker exec "${APP_CONTAINER}" supervisorctl stop "${program}" >/dev/null
    done < <(awk '$2 == "RUNNING" && $1 !~ /celery.*beat/ && $1 ~ /celery/ {print $1}' "${status_file}")

    if ! docker exec "${APP_CONTAINER}" sh -c \
        "if command -v pgrep >/dev/null 2>&1; then ! pgrep -f '[c]elery.*worker' >/dev/null; else ! ps ax | grep -E '[c]elery.*worker' >/dev/null; fi"; then
        fail "Celery worker processes remain after graceful stop"
    fi
}

# ============================================
# 冻结全部业务写入
#
# worker 排空后停止整个 tdyw 容器，确保遗漏的后台进程也无法写 DB 或文件。
# tdyw-db 不停止，InnoDB 逻辑备份使用 single-transaction 获取一致性视图。
# ============================================
freeze_application() {
    CURRENT_STAGE="freeze_application"
    FREEZE_STARTED_EPOCH="$(date +%s)"
    stop_supervisor_programs
    log "Stopping application container ${APP_CONTAINER}; database remains running"
    if ! docker stop -t "${APP_STOP_TIMEOUT}" "${APP_CONTAINER}" >/dev/null; then
        container_running "${APP_CONTAINER}" || APP_STOPPED=1
        fail "failed to stop application container ${APP_CONTAINER}"
    fi
    APP_STOPPED=1
    container_running "${APP_CONTAINER}" && fail "application container is still running"
    container_running "${DB_CONTAINER}" || fail "database container stopped unexpectedly"
    log "Business writes are frozen"
}

# ============================================
# 凭据注入与 MariaDB 逻辑备份
#
# client cnf 先复制到数据库容器临时目录并 chmod 600。--defaults-extra-file 是 dump 的
# 第一个选项，密码不会出现在命令行。成功后必须同时通过非空、gzip 和表结构检查。
# ============================================
prepare_database_credentials() {
    CONTAINER_CNF="/tmp/tdyw_backup_$$.cnf"
    docker cp "${BACKUP_CLIENT_CNF}" "${DB_CONTAINER}:${CONTAINER_CNF}" >/dev/null
    docker exec "${DB_CONTAINER}" chmod 600 "${CONTAINER_CNF}"
}

validate_database_credentials() {
    local client_bin
    CURRENT_STAGE="database_credentials"
    prepare_database_credentials
    client_bin="$(docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb || command -v mysql')"
    if ! DB_ACCOUNT="$(docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 --batch --skip-column-names \
        -e 'SELECT CURRENT_USER()' "${DB_NAME}")"; then
        fail "backup client cnf authentication failed"
    fi
    DB_ACCOUNT="${DB_ACCOUNT//$'\r'/}"
    [ -n "${DB_ACCOUNT}" ] && [[ "${DB_ACCOUNT}" != *$'\n'* ]] || \
        fail "could not determine the authenticated database account"
    if ! docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 --batch --skip-column-names \
        -e 'SELECT 1 FROM django_migrations LIMIT 1' "${DB_NAME}" >/dev/null; then
        fail "database account from backup client cnf lacks SELECT privilege on ${DB_NAME}"
    fi
    docker exec "${DB_CONTAINER}" rm -f -- "${CONTAINER_CNF}" >/dev/null
    CONTAINER_CNF=""
    CURRENT_STAGE="preflight"
    log "Database credential and SELECT privilege check passed (account=${DB_ACCOUNT})"
}

backup_database_logical() {
    CURRENT_STAGE="database_dump"
    local dump_bin
    prepare_database_credentials
    dump_bin="$(docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb-dump || command -v mysqldump')"
    [ -n "${dump_bin}" ] || fail "mariadb-dump/mysqldump is unavailable"
    log "Creating consistent logical dump as ${DB_ACCOUNT}"
    if ! docker exec "${DB_CONTAINER}" "${dump_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 \
        --single-transaction --routines --triggers --events --quick --hex-blob \
        --default-character-set=utf8mb4 --set-charset --skip-lock-tables \
        "${DB_NAME}" 2>"${TEMP_DIR}/database.stderr.log" | gzip -c > "${TEMP_DIR}/database.sql.gz"; then
        fail "mariadb-dump failed; see database.stderr.log"
    fi
    [ -s "${TEMP_DIR}/database.sql.gz" ] || fail "database dump is empty"
    gzip -t "${TEMP_DIR}/database.sql.gz" || fail "database dump gzip validation failed"
    zgrep -q -E '(^|[[:space:]])CREATE TABLE|Table structure for table' "${TEMP_DIR}/database.sql.gz" || \
        fail "database dump does not contain expected table structure"
    rm -f -- "${TEMP_DIR}/database.stderr.log"
}

# ============================================
# MariaDB 物理备份
#
# 主脚本持有全局锁并已冻结全部业务写入。worker 只执行 mariabackup 和产物校验，
# 不得自行发布备份集、清理保留期或启停应用。物理备份覆盖整个 MariaDB server
# instance，恢复时会覆盖完整数据目录，不等同于只恢复 DB_NAME。
# ============================================
backup_database_physical() {
    CURRENT_STAGE="database_physical"
    prepare_database_credentials
    log "Creating physical MariaDB server-instance backup as ${DB_ACCOUNT}"
    if ! BACKUP_ORCHESTRATED=YES \
        DB_CONTAINER="${DB_CONTAINER}" \
        CONTAINER_CNF="${CONTAINER_CNF}" \
        PHYSICAL_OUTPUT_FILE="${TEMP_DIR}/database.mariabackup.tar.gz" \
        PHYSICAL_LOG_FILE="${TEMP_DIR}/database-physical.stderr.log" \
        bash "${PHYSICAL_BACKUP_WORKER}"; then
        fail "mariabackup failed; see database-physical.stderr.log"
    fi
    [ -s "${TEMP_DIR}/database.mariabackup.tar.gz" ] || fail "physical database artifact is empty"
    tar -tzf "${TEMP_DIR}/database.mariabackup.tar.gz" >/dev/null || \
        fail "physical database archive validation failed"
    rm -f -- "${TEMP_DIR}/database-physical.stderr.log"
}

# ============================================
# documents/media 独立全量快照
#
# 应用容器已经停止，但 volume 仍可通过 --volumes-from 以只读方式挂载到短生命周期 helper。
# Python 快照工具支持特殊文件名，拒绝符号链接/特殊文件，并检测归档期间的状态变化。
# 每个归档都包含目标文件集的全部目录和文件，不引用其他备份集。
# ============================================
backup_fileset() {
    local name="$1" source="$2"
    CURRENT_STAGE="${name}_archive"
    log "Creating independent full ${name} snapshot from the stopped application volume"
    docker run --rm --network none \
        --volumes-from "${APP_CONTAINER}:ro" \
        -v "${SCRIPT_DIR}:/backup-code:ro" \
        -v "${TEMP_DIR}:/backup-output" \
        --entrypoint python3 "${APP_IMAGE}" \
        /backup-code/create_fileset_snapshot.py \
        --name "${name}" --source "${source}" \
        --archive "/backup-output/${name}.tar.gz" \
        --manifest "/backup-output/${name}.manifest.json" \
        --backup-set-id "${BACKUP_SET_ID}"
    tar -tzf "${TEMP_DIR}/${name}.tar.gz" >/dev/null || fail "${name} tar validation failed"
    [ -s "${TEMP_DIR}/${name}.manifest.json" ] || fail "${name} snapshot manifest is empty"
}

# ============================================
# 根 manifest
#
# VERIFYING 在产物初检阶段生成；只有服务恢复并再次校验后才改写为 SUCCESS。
# manifest 记录数据库服务端版本、镜像、文件统计、停写时长和明确排除项。
# ============================================
build_manifest() {
    local status="$1" finished_at="$2" db_version db_image_id db_digest git_commit client_bin
    local -a database_artifact_args=()
    client_bin="$(docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb || command -v mysql')"
    db_version="$(docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 \
        --batch --skip-column-names -e 'SELECT VERSION()' "${DB_NAME}")"
    db_image_id="$(docker image inspect -f '{{.Id}}' "${DB_IMAGE}" 2>/dev/null || true)"
    db_digest="$(docker image inspect -f '{{join .RepoDigests ","}}' "${DB_IMAGE}" 2>/dev/null || true)"
    git_commit="$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    database_artifact_args+=(--logical-database-artifact /backup-output/database.sql.gz)
    if [ "${DB_BACKUP_MODE}" = "both" ]; then
        database_artifact_args+=(--physical-database-artifact /backup-output/database.mariabackup.tar.gz)
    fi
    docker run --rm --network none \
        -v "${SCRIPT_DIR}:/backup-code:ro" \
        -v "${TEMP_DIR}:/backup-output" \
        --entrypoint python3 "${APP_IMAGE}" \
        /backup-code/create_backup_set_manifest.py \
        --output /backup-output/manifest.json \
        --backup-set-id "${BACKUP_SET_ID}" --status "${status}" \
        --started-at "${STARTED_AT}" --finished-at "${finished_at}" \
        --hostname "$(hostname)" --database-name "${DB_NAME}" \
        --database-account "${DB_ACCOUNT}" \
        --database-version "${db_version}" --database-image "${DB_IMAGE}" \
        --database-image-id "${db_image_id}" --database-image-digest "${db_digest}" \
        --app-image "${APP_IMAGE}" --git-commit "${git_commit}" \
        --freeze-seconds "${FREEZE_SECONDS}" \
        --database-mode "${DB_BACKUP_MODE}" \
        "${database_artifact_args[@]}" \
        --documents-manifest /backup-output/documents.manifest.json \
        --media-manifest /backup-output/media.manifest.json
}

# ============================================
# 完整性校验
#
# SHA256SUMS 覆盖 DB、两个归档、两个 fileset manifest 和根 manifest。根 manifest 状态
# 从 VERIFYING 改为 SUCCESS 后必须重新生成并再次验证 SHA256SUMS。
# ============================================
generate_and_verify_checksums() {
    CURRENT_STAGE="sha256"
    local -a artifacts=(database.sql.gz documents.tar.gz media.tar.gz \
        documents.manifest.json media.manifest.json manifest.json)
    if [ "${DB_BACKUP_MODE}" = "both" ]; then
        artifacts=(database.mariabackup.tar.gz "${artifacts[@]}")
    fi
    (
        cd "${TEMP_DIR}"
        sha256sum "${artifacts[@]}" > SHA256SUMS
        sha256sum -c --strict SHA256SUMS
    )
}

verify_all_artifacts() {
    CURRENT_STAGE="verify_artifacts"
    [ -s "${TEMP_DIR}/database.sql.gz" ] || fail "logical database artifact is empty"
    gzip -t "${TEMP_DIR}/database.sql.gz"
    zgrep -q -E '(^|[[:space:]])CREATE TABLE|Table structure for table' "${TEMP_DIR}/database.sql.gz" || \
        fail "database dump does not contain expected table structure"
    if [ "${DB_BACKUP_MODE}" = "both" ]; then
        [ -s "${TEMP_DIR}/database.mariabackup.tar.gz" ] || fail "physical database artifact is empty"
        tar -tzf "${TEMP_DIR}/database.mariabackup.tar.gz" >/dev/null
    fi
    [ -s "${TEMP_DIR}/documents.tar.gz" ] || fail "documents artifact is empty"
    [ -s "${TEMP_DIR}/media.tar.gz" ] || fail "media artifact is empty"
    tar -tzf "${TEMP_DIR}/documents.tar.gz" >/dev/null
    tar -tzf "${TEMP_DIR}/media.tar.gz" >/dev/null
    generate_and_verify_checksums
}

# ============================================
# 保留策略
#
# 默认不删除。显式启用后，每个通过完整校验且超过保留期的独立全量备份可单独删除。
# ============================================
cleanup_retention() {
    if ! is_yes "${RETENTION_DELETE}"; then
        log "Retention deletion disabled (RETENTION_DELETE=${RETENTION_DELETE})"
        return 0
    fi
    CURRENT_STAGE="retention"
    local candidate resolved_root
    resolved_root="$(cd "${BACKUP_ROOT}" && pwd)"
    while IFS= read -r -d '' candidate; do
        [ "${candidate}" != "${FINAL_DIR}" ] || continue
        [[ "$(basename "${candidate}")" =~ ^backup_set_[0-9]{8}_[0-9]{6}$ ]] || continue
        [ "$(dirname "${candidate}")" = "${resolved_root}" ] || fail "retention candidate escaped backup root"
        rm -rf -- "${candidate}"
        log "Removed expired verified full backup set: ${candidate}"
    done < <(python3 "${SCRIPT_DIR}/select_retention_chains.py" \
        --backup-root "${resolved_root}" --retention-days "${RETENTION_DAYS}")
}

# ============================================
# 主流程
# ============================================
main() {
    if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
        usage
        return 0
    fi
    [ "$#" -eq 0 ] || fail "unknown argument: $1 (use --help)"
    if ! is_yes "${DRY_RUN}"; then
        # Retention must not race a backup or restore operation.
        acquire_maintenance_lock
    fi
    preflight
    check_disk_space
    print_plan
    if is_yes "${DRY_RUN}"; then
        log "DRY_RUN complete: no lock, service stop, backup, or retention deletion was performed"
        return 0
    fi

    initialize_backup_workdir
    freeze_application
    # 每个成功备份集都包含目标日期的独立逻辑全量，避免数据库增量链依赖。
    backup_database_logical
    if [ "${DB_BACKUP_MODE}" = "both" ]; then
        backup_database_physical
    fi
    backup_fileset documents "${DOCUMENTS_PATH}"
    backup_fileset media "${MEDIA_PATH}"

    FREEZE_SECONDS=$(($(date +%s) - FREEZE_STARTED_EPOCH))
    CURRENT_STAGE="manifest_verifying"
    build_manifest VERIFYING ""
    verify_all_artifacts

    CURRENT_STAGE="restore_application"
    restore_application

    FREEZE_SECONDS=$(($(date +%s) - FREEZE_STARTED_EPOCH))
    CURRENT_STAGE="manifest_success"
    build_manifest SUCCESS "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    generate_and_verify_checksums

    CURRENT_STAGE="publish"
    mv -- "${TEMP_DIR}" "${FINAL_DIR}"
    TEMP_DIR=""
    log "Backup set published atomically: ${FINAL_DIR}"
    log "Write freeze duration: ${FREEZE_SECONDS}s"
    cleanup_retention
}

main "$@"
