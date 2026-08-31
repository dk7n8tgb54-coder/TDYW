#!/usr/bin/env bash
# ================================================================================
# TDYW BorgBackup 一致性备份入口
# --------------------------------------------------------------------------------
# 思路：冻结应用写入 → mariadb-dump 导出 DB → 归档 binlog → 与 documents/media 卷一起 borg create
#       打进同一个 archive。四者来自同一停写窗口，即一致性备份。
#
# 仓库：本地 borg repo（加密 repokey-blake2），路径从 borg.env 的 BORG_REPO 读取。
#       BORG_PASSPHRASE 必需，用于访问加密 repo。
#
# 远程推送（PUSH_REMOTE=YES 时启用）：本地 archive 创建并校验后、应用解冻前，
#       向远程机的独立 borg repo 推送一份去重增量 archive（与本地同一停写窗口，数据一致）。
#       远程机需先 borg init repo + 配 SSH 免密。不启用时在 borg.env 中设 PUSH_REMOTE=NO。
#
# 一致性流程：
#   获取全局锁 → 前置检查 → 停入口/beat/worker → 停 tdyw 容器（DB 保持运行）
#   → mariadb-dump --single-transaction → archive_binlog（FLUSH BINARY LOGS + 复制 binlog）
#   → borg create（dump + documents卷 + media卷 + binlog + manifest）
#   → borg check --repository-only → 可选 borg create 远程仓库（PUSH_REMOTE=YES 时，推远程机）
#   → 启动 tdyw + 健康检查 → borg prune（GFS）+ borg compact（回收磁盘空间）
#   （本地与远程 archive 都落盘并校验后才解冻恢复应用；prune/compact 在恢复后执行，不占停机窗口）
#
# 产物：一个 borg archive（命名 tdyw-YYYYMMDD-HHMMSS），含：
#   - database.sql.gz（mariadb-dump 逻辑全量）
#   - documents 卷原始目录树（块级去重）
#   - media 卷原始目录树（块级去重）
#   - manifest.json（DB 版本/git commit/volume 路径/时间戳/binlog 位点）
#   - binlog/（已完成 binlog 文件 + 索引；用于 PITR 按时间点恢复）
#
# 禁止：直接 borg 备份运行中的 /var/lib/mysql（InnoDB 不一致）。DB 必须逻辑 dump。
#
# 用法：
#   1. dry-run（只 preflight + 验证凭据登录，不冻结不创建 archive）
#      BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
#      DOCUMENTS_VOLUME=docker_tdyw-documents MEDIA_VOLUME=docker_tdyw-media \
#      ./borgbackup/borg_backup_set_create.sh
#
#   2. 正式备份（仅本地 repo）
#      BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
#      DOCUMENTS_VOLUME=docker_tdyw-documents MEDIA_VOLUME=docker_tdyw-media \
#      DRY_RUN=NO ./borgbackup/borg_backup_set_create.sh
#
#   3. 正式备份 + 推远程（borg.env 里设 PUSH_REMOTE=YES + BORG_REMOTE_REPO + BORG_REMOTE_PASSPHRASE）
#      BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
#      DOCUMENTS_VOLUME=docker_tdyw-documents MEDIA_VOLUME=docker_tdyw-media \
#      DRY_RUN=NO ./borgbackup/borg_backup_set_create.sh
#      （borg.env 里设 PUSH_REMOTE=YES + BORG_REMOTE_REPO + BORG_REMOTE_PASSPHRASE）
#
# 主要环境变量：
#   APP_CONTAINER       应用容器，默认 tdyw
#   DB_CONTAINER        数据库容器，默认 tdyw-db
#   DB_NAME             数据库名；未设置时从 DB 容器 MYSQL_DATABASE 读取
#   BACKUP_CLIENT_CNF   MariaDB client cnf（0600/0400），复用 backup_set 的
#   DOCUMENTS_VOLUME    documents docker volume 名
#   MEDIA_VOLUME        media docker volume 名
#   MYSQL_DATA_VOLUME   MySQL 数据卷名（存 binlog），默认 docker_tdyw-mysql-data
#   BORG_ENV_FILE       borg 配置文件（0600），含 BORG_REPO / BORG_PASSPHRASE
#                       （+ 可选 BORG_REMOTE_REPO / BORG_REMOTE_PASSPHRASE / PUSH_REMOTE）
#   BORG_COMPRESSION    默认 zstd,3
#   PRUNE_KEEP_WITHIN / PRUNE_KEEP_DAILY / PRUNE_KEEP_WEEKLY / PRUNE_KEEP_MONTHLY
#                       本地保留策略，默认 2d / 7 / 4 / 6（可在 borg.env 中覆盖）
#   REMOTE_PRUNE_KEEP_WITHIN / REMOTE_PRUNE_KEEP_DAILY / REMOTE_PRUNE_KEEP_WEEKLY /
#   REMOTE_PRUNE_KEEP_MONTHLY
#                       远程保留策略，默认 7d / 14 / 8 / 12（可在 borg.env 中覆盖）
#   BORG_RSH            远程 SSH 命令，默认 ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new
#                       （用默认 SSH key；如需指定 key 在 borg.env 中设 BORG_RSH="ssh -i /path/to/key ..."）
#   DRY_RUN             YES（默认，只 preflight）/ NO
#   APP_STOP_TIMEOUT    停止应用最大等待秒数，默认 900
#   HEALTH_TIMEOUT      启动后健康检查最大等待秒数，默认 180
#   LOCK_FILE           全局锁，默认 /data/backups/tdyw/.backup.lock（与 backup_set 共享）
# ================================================================================

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_CONTAINER="${APP_CONTAINER:-tdyw}"
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
DB_NAME="${DB_NAME:-}"
BACKUP_CLIENT_CNF="${BACKUP_CLIENT_CNF:-/opt/docker/borgbackup/tdyw_backup.cnf}"
DOCUMENTS_VOLUME="${DOCUMENTS_VOLUME:-docker_tdyw-documents}"
MEDIA_VOLUME="${MEDIA_VOLUME:-docker_tdyw-media}"
DOCUMENTS_PATH="${DOCUMENTS_PATH:-/data/spug/spug_api/storage/documents}"
MEDIA_PATH="${MEDIA_PATH:-/data/spug/spug_api/media}"
MYSQL_DATA_VOLUME="${MYSQL_DATA_VOLUME:-docker_tdyw-mysql-data}"

BORG_ENV_FILE="${BORG_ENV_FILE:-/opt/docker/borgbackup/borg.env}"
BORG_REPO="${BORG_REPO:-}"
BORG_PASSPHRASE="${BORG_PASSPHRASE:-}"
BORG_REMOTE_REPO="${BORG_REMOTE_REPO:-}"
BORG_REMOTE_PASSPHRASE="${BORG_REMOTE_PASSPHRASE:-}"
PUSH_REMOTE="${PUSH_REMOTE:-NO}"
BORG_COMPRESSION="${BORG_COMPRESSION:-zstd,3}"
BORG_RSH="${BORG_RSH:-ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new}"

# 保留策略（可在 borg.env 中覆盖；KEEP_WITHIN 为 borg 时长格式，如 2d/1w/30d）
PRUNE_KEEP_WITHIN="${PRUNE_KEEP_WITHIN:-2d}"
PRUNE_KEEP_DAILY="${PRUNE_KEEP_DAILY:-7}"
PRUNE_KEEP_WEEKLY="${PRUNE_KEEP_WEEKLY:-4}"
PRUNE_KEEP_MONTHLY="${PRUNE_KEEP_MONTHLY:-6}"
REMOTE_PRUNE_KEEP_WITHIN="${REMOTE_PRUNE_KEEP_WITHIN:-7d}"
REMOTE_PRUNE_KEEP_DAILY="${REMOTE_PRUNE_KEEP_DAILY:-14}"
REMOTE_PRUNE_KEEP_WEEKLY="${REMOTE_PRUNE_KEEP_WEEKLY:-8}"
REMOTE_PRUNE_KEEP_MONTHLY="${REMOTE_PRUNE_KEEP_MONTHLY:-12}"

DRY_RUN="${DRY_RUN:-YES}"
APP_STOP_TIMEOUT="${APP_STOP_TIMEOUT:-900}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
LOCK_FILE="${LOCK_FILE:-/data/backups/tdyw/.backup.lock}"
MIN_FREE_PERCENT="${MIN_FREE_PERCENT:-15}"

BACKUP_SET_ID="tdyw-$(date -u '+%Y%m%d-%H%M%S')"
ARCHIVE_NAME="${BACKUP_SET_ID}"
RUNTIME_DIR=""
APP_NEEDS_RESTART=0
APP_STOPPED=0
FREEZE_STARTED_EPOCH=0
FREEZE_SECONDS=0
DUMP_FILE=""
MANIFEST_FILE=""
DOCS_MP=""
MED_MP=""
DB_ACCOUNT=""
DB_VERSION=""
CONTAINER_CNF=""
LOCAL_ARCHIVE_CREATED=0
LOCAL_ARCHIVE_VERIFIED=0
REMOTE_ARCHIVE_CREATED=0
REMOTE_ARCHIVE_VERIFIED=0
CURRENT_STAGE="preflight"
STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
BINLOG_DIR=""
BINLOG_FILE=""
BINLOG_POS=""

# ============================================
# 通用工具
# ============================================
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ERROR: $*" >&2; return 1; }
is_yes() { case "${1^^}" in YES|TRUE|1) return 0 ;; *) return 1 ;; esac; }
validate_number() { [[ "$2" =~ ^[0-9]+$ ]] || fail "$1 must be a non-negative integer"; }
container_running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]; }

# 早期 borg 1.2.x 的 compact 不支持 --stats，用 du 前后差值记录实际释放的磁盘空间
repo_disk_usage() { du -sb "$1" 2>/dev/null | awk '{print $1}'; }

human_bytes() {
    awk -v b="$1" 'BEGIN {
        split("B KiB MiB GiB TiB", u, " "); i = 1
        while (b >= 1024 && i < 5) { b /= 1024; i++ }
        printf "%.2f %s", b, u[i]
    }'
}

# ============================================
# 应用恢复与健康检查（复用 backup_set 逻辑）
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
    [ "${APP_NEEDS_RESTART}" -eq 1 ] || return 0
    log "Restoring application container ${APP_CONTAINER}"
    if container_running "${APP_CONTAINER}"; then
        docker restart -t "${APP_STOP_TIMEOUT}" "${APP_CONTAINER}" >/dev/null || fail "failed to restart ${APP_CONTAINER}"
    else
        docker start "${APP_CONTAINER}" >/dev/null || fail "failed to start ${APP_CONTAINER}"
    fi
    APP_STOPPED=0
    APP_NEEDS_RESTART=0
    wait_for_app_health
}

# ============================================
# 失败状态与统一 trap
# ============================================
write_failure_marker() {
    local rc="$1"
    [ -n "${RUNTIME_DIR}" ] && [ -d "${RUNTIME_DIR}" ] || return 0
    printf '{\n  "backup_set_id": "%s",\n  "status": "FAILED",\n  "failure_stage": "%s",\n  "exit_code": %s\n}\n' \
        "${BACKUP_SET_ID}" "${CURRENT_STAGE//[^a-zA-Z0-9_.-]/_}" "${rc}" > "${RUNTIME_DIR}/FAILED.json"
    log "Failed backup retained for diagnosis: ${RUNTIME_DIR}/FAILED.json"
}

cleanup() {
    local rc=$?
    local failure_stage="${CURRENT_STAGE}"
    trap - EXIT INT TERM
    set +e
    FREEZE_SECONDS=$(($(date +%s) - FREEZE_STARTED_EPOCH))
    # 失败时只删除“已创建但未通过校验”的 archive（本地 + 远程），避免 borg list 出现半成品。
    # 已通过校验的 archive 即使后续 prune/compact/远程推送失败也保留，防止丢掉当次有效备份。
    if [ "${LOCAL_ARCHIVE_CREATED}" -eq 1 ] && [ "${LOCAL_ARCHIVE_VERIFIED}" -ne 1 ] && [ "${rc}" -ne 0 ]; then
        CURRENT_STAGE="cleanup_local_archive"
        log "deleting unverified local archive ${ARCHIVE_NAME}"
        borg delete --stats "${BORG_REPO}::${ARCHIVE_NAME}" >/dev/null 2>&1 || true
    fi
    if [ "${REMOTE_ARCHIVE_CREATED}" -eq 1 ] && [ "${REMOTE_ARCHIVE_VERIFIED}" -ne 1 ] && [ "${rc}" -ne 0 ]; then
        CURRENT_STAGE="cleanup_remote_archive"
        log "deleting unverified remote archive ${ARCHIVE_NAME}"
        BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" BORG_RSH="${BORG_RSH}" \
            borg delete --stats "${BORG_REMOTE_REPO}::${ARCHIVE_NAME}" >/dev/null 2>&1 || true
    fi
    # 清理 DB 容器内临时 cnf
    if [ -n "${CONTAINER_CNF}" ]; then
        docker exec "${DB_CONTAINER}" rm -f -- "${CONTAINER_CNF}" >/dev/null 2>&1 || true
    fi
    # 失败时恢复应用
    if [ "${APP_NEEDS_RESTART}" -eq 1 ]; then
        CURRENT_STAGE="restore_after_failure"
        if ! restore_application; then
            rc=1
            failure_stage="restore_after_failure"
        fi
    fi
    if [ "${rc}" -ne 0 ]; then
        CURRENT_STAGE="${failure_stage}"
        write_failure_marker "${rc}"
    fi
    if [ -n "${RUNTIME_DIR}" ] && [ -d "${RUNTIME_DIR}" ]; then
        if [ "${rc}" -ne 0 ] && [ -f "${RUNTIME_DIR}/FAILED.json" ]; then
            # 失败时仅保留 FAILED.json 供诊断，其余临时文件（含 binlog 副本）清理
            find "${RUNTIME_DIR}" -mindepth 1 ! -name FAILED.json -delete
        else
            rm -rf -- "${RUNTIME_DIR}"
        fi
    fi
    exit "${rc}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ============================================
# 加载 borg 配置 + 解析 volume 路径
# ============================================
load_borg_env() {
    [ -f "${BORG_ENV_FILE}" ] || fail "borg env file missing: ${BORG_ENV_FILE}"
    local mode; mode="$(stat -c '%a' "${BORG_ENV_FILE}" 2>/dev/null || true)"
    case "${mode}" in 600|400) ;; *) fail "borg.env must have mode 0600 or 0400" ;; esac
    # shellcheck disable=SC1090
    set -a; . "${BORG_ENV_FILE}"; set +a
    [ -n "${BORG_REPO:-}" ] || fail "BORG_REPO is empty in ${BORG_ENV_FILE}"
    [ -n "${BORG_PASSPHRASE:-}" ] || fail "BORG_PASSPHRASE is empty in ${BORG_ENV_FILE} (encrypted repo requires passphrase)"
    if is_yes "${PUSH_REMOTE}"; then
        [ -n "${BORG_REMOTE_REPO:-}" ] || fail "PUSH_REMOTE=YES but BORG_REMOTE_REPO is empty"
        [ -n "${BORG_REMOTE_PASSPHRASE:-}" ] || fail "PUSH_REMOTE=YES but BORG_REMOTE_PASSPHRASE is empty"
    fi
    export BORG_REPO BORG_PASSPHRASE BORG_REMOTE_REPO BORG_REMOTE_PASSPHRASE PUSH_REMOTE
}

resolve_volumes() {
    DOCS_MP="$(docker volume inspect -f '{{.Mountpoint}}' "${DOCUMENTS_VOLUME}" 2>/dev/null || true)"
    MED_MP="$(docker volume inspect -f '{{.Mountpoint}}' "${MEDIA_VOLUME}" 2>/dev/null || true)"
    [ -n "${DOCS_MP}" ] && [ -d "${DOCS_MP}" ] || fail "documents volume mountpoint not found: ${DOCUMENTS_VOLUME}"
    [ -n "${MED_MP}" ] && [ -d "${MED_MP}" ] || fail "media volume mountpoint not found: ${MEDIA_VOLUME}"
}

# ============================================
# 前置检查
# ============================================
preflight() {
    CURRENT_STAGE="preflight"
    command -v borg >/dev/null || fail "borg is required"
    command -v docker >/dev/null || fail "docker is required"
    command -v flock >/dev/null || fail "flock is required"
    command -v gzip >/dev/null || fail "gzip is required"
    command -v python3 >/dev/null || fail "python3 is required"

    validate_number APP_STOP_TIMEOUT "${APP_STOP_TIMEOUT}"
    validate_number HEALTH_TIMEOUT "${HEALTH_TIMEOUT}"
    validate_number MIN_FREE_PERCENT "${MIN_FREE_PERCENT}"

    container_running "${APP_CONTAINER}" || fail "application container is not running: ${APP_CONTAINER}"
    container_running "${DB_CONTAINER}" || fail "database container is not running: ${DB_CONTAINER}"

    docker exec "${APP_CONTAINER}" test -d "${DOCUMENTS_PATH}" || fail "documents path is missing in app container"
    docker exec "${APP_CONTAINER}" test -d "${MEDIA_PATH}" || fail "media path is missing in app container"
    docker exec "${APP_CONTAINER}" supervisorctl status >/dev/null || fail "supervisorctl is unavailable in the application container"
    docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb-dump >/dev/null || command -v mysqldump >/dev/null' || \
        fail "mariadb-dump/mysqldump is unavailable in ${DB_CONTAINER}"
    docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb >/dev/null || command -v mysql >/dev/null' || \
        fail "mariadb/mysql client is unavailable in ${DB_CONTAINER}"

    [ -e "${BACKUP_CLIENT_CNF}" ] || fail "backup client cnf is missing: ${BACKUP_CLIENT_CNF}"
    [ -f "${BACKUP_CLIENT_CNF}" ] || fail "backup client cnf is not a regular file"
    [ -r "${BACKUP_CLIENT_CNF}" ] || fail "backup client cnf is not readable by $(id -un)"
    ! grep -q 'REPLACE_WITH_' "${BACKUP_CLIENT_CNF}" || fail "backup client cnf still contains a template placeholder"
    local cnf_mode; cnf_mode="$(stat -c '%a' "${BACKUP_CLIENT_CNF}" 2>/dev/null || true)"
    case "${cnf_mode}" in 600|400) ;; *) fail "backup client cnf must have mode 0600 or 0400" ;; esac

    load_borg_env
    # DB_NAME 在 load_borg_env 之后解析，防止 borg.env 中的空赋值覆盖自动探测值
    [ -z "${DB_NAME}" ] && DB_NAME="$(docker exec "${DB_CONTAINER}" sh -c 'printf %s "${MYSQL_DATABASE:-}"')"
    [ -n "${DB_NAME}" ] || fail "DB_NAME is empty and MYSQL_DATABASE is unavailable in ${DB_CONTAINER}"
    # 保留策略参数校验（在 load_borg_env 之后，确保读到 borg.env 的覆盖值）
    validate_number PRUNE_KEEP_DAILY "${PRUNE_KEEP_DAILY}"
    validate_number PRUNE_KEEP_WEEKLY "${PRUNE_KEEP_WEEKLY}"
    validate_number PRUNE_KEEP_MONTHLY "${PRUNE_KEEP_MONTHLY}"
    validate_number REMOTE_PRUNE_KEEP_DAILY "${REMOTE_PRUNE_KEEP_DAILY}"
    validate_number REMOTE_PRUNE_KEEP_WEEKLY "${REMOTE_PRUNE_KEEP_WEEKLY}"
    validate_number REMOTE_PRUNE_KEEP_MONTHLY "${REMOTE_PRUNE_KEEP_MONTHLY}"
    [ -n "${PRUNE_KEEP_WITHIN}" ] || fail "PRUNE_KEEP_WITHIN is empty"
    [ -n "${REMOTE_PRUNE_KEEP_WITHIN}" ] || fail "REMOTE_PRUNE_KEEP_WITHIN is empty"
    resolve_volumes

    # 本地 borg repo 可访问（BORG_PASSPHRASE 已 export，加密 repo 可读）
    borg info >/dev/null 2>&1 || borg list >/dev/null 2>&1 || fail "local borg repo inaccessible: ${BORG_REPO}"
    # 远程 repo 连通性（仅 PUSH_REMOTE=YES 时检查，预留扩展）
    if is_yes "${PUSH_REMOTE}"; then
        BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" BORG_RSH="${BORG_RSH}" \
            borg info "${BORG_REMOTE_REPO}" >/dev/null 2>&1 || fail "remote borg repo inaccessible: ${BORG_REMOTE_REPO}"
    fi
    # 凭据登录 + SELECT 权限验证（dry-run 也执行，提前暴露密码/权限问题）
    validate_database_credentials
}

# ============================================
# 磁盘空间检查
# ============================================
check_disk_space() {
    CURRENT_STAGE="disk_space"
    local probe="${BORG_REPO}" used_percent free_percent
    while [ ! -e "${probe}" ] && [ "${probe}" != "/" ]; do probe="$(dirname "${probe}")"; done
    used_percent="$(df -P "${probe}" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
    [[ "${used_percent}" =~ ^[0-9]+$ ]] || fail "could not determine backup filesystem usage"
    free_percent=$((100 - used_percent))
    [ "${free_percent}" -ge "${MIN_FREE_PERCENT}" ] || \
        fail "backup filesystem has ${free_percent}% free; minimum is ${MIN_FREE_PERCENT}%"
    log "Disk check passed: ${free_percent}% free"
}

# ============================================
# 执行计划
# ============================================
print_plan() {
    cat <<PLAN
backup_set_id=${BACKUP_SET_ID}
application_container=${APP_CONTAINER}
database_container=${DB_CONTAINER}
database_name=${DB_NAME}
documents_volume=${DOCUMENTS_VOLUME} -> ${DOCS_MP}
media_volume=${MEDIA_VOLUME} -> ${MED_MP}
mysql_data_volume=${MYSQL_DATA_VOLUME}
borg_repo=${BORG_REPO} (encrypted, repokey-blake2)
push_remote=${PUSH_REMOTE}
remote_borg_repo=${BORG_REMOTE_REPO:-<none>}
compression=${BORG_COMPRESSION}
dry_run=${DRY_RUN}
PLAN
}

# ============================================
# 全局维护锁
# ============================================
acquire_maintenance_lock() {
    CURRENT_STAGE="lock"
    mkdir -p -- "$(dirname "${LOCK_FILE}")"
    chmod 700 "$(dirname "${LOCK_FILE}")"
    exec 9>"${LOCK_FILE}"
    flock -n 9 || fail "another backup or restore operation is already running"
}

initialize_workdir() {
    RUNTIME_DIR="$(mktemp -d /tmp/tdyw-borg.XXXXXX)"
    chmod 700 "${RUNTIME_DIR}"
}

# ============================================
# 停止入口、beat 和写 worker（复用 backup_set）
# 顺序：先关入口阻断新任务 → 关 beat 阻断定时任务 → 让 worker 完成当前任务退出
# ============================================
stop_supervisor_programs() {
    local status_file="${RUNTIME_DIR}/supervisor.before" program
    docker exec "${APP_CONTAINER}" supervisorctl status > "${status_file}"
    APP_NEEDS_RESTART=1

    # 1. Stop ingress first so no new HTTP/WebSocket work can be accepted.
    for program in nginx spug-api spug-api-upload spug-ws; do
        if awk -v name="${program}" '$1 == name && $2 == "RUNNING" {found=1} END {exit !found}' "${status_file}"; then
            log "Gracefully stopping ${program}"
            docker exec "${APP_CONTAINER}" supervisorctl stop "${program}" >/dev/null
        fi
    done

    # 2. Beat must stop before workers, preventing new scheduled tasks.
    while IFS= read -r program; do
        [ -n "${program}" ] || continue
        log "Gracefully stopping ${program}"
        docker exec "${APP_CONTAINER}" supervisorctl stop "${program}" >/dev/null
    done < <(awk '$2 == "RUNNING" && $1 ~ /celery.*beat/ {print $1}' "${status_file}")

    # 3. Every Celery worker is treated as a writer unless proven otherwise.
    while IFS= read -r program; do
        [ -n "${program}" ] || continue
        log "Gracefully draining ${program}"
        docker exec "${APP_CONTAINER}" supervisorctl stop "${program}" >/dev/null
    done < <(awk '$2 == "RUNNING" && $1 !~ /celery.*beat/ && $1 ~ /celery/ {print $1}' "${status_file}")

    # 4. Verify no celery worker process remains.
    if ! docker exec "${APP_CONTAINER}" sh -c \
        "if command -v pgrep >/dev/null 2>&1; then ! pgrep -f '[c]elery.*worker' >/dev/null; else ! ps ax | grep -E '[c]elery.*worker' >/dev/null; fi"; then
        fail "Celery worker processes remain after graceful stop"
    fi
}

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
# 凭据注入 + MariaDB 逻辑备份
# cnf 复制到 DB 容器 /tmp，chmod 600；--defaults-extra-file 是 dump 第一参数，密码不进 argv
# ============================================
prepare_database_credentials() {
    CONTAINER_CNF="/tmp/tdyw_borg_$$.cnf"
    docker cp "${BACKUP_CLIENT_CNF}" "${DB_CONTAINER}:${CONTAINER_CNF}" >/dev/null
    docker exec "${DB_CONTAINER}" chmod 600 "${CONTAINER_CNF}"
}

validate_database_credentials() {
    CURRENT_STAGE="database_credentials"
    prepare_database_credentials
    local client_bin
    client_bin="$(docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb || command -v mysql')"
    if ! DB_ACCOUNT="$(docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 --batch --skip-column-names \
        -e 'SELECT CURRENT_USER()' "${DB_NAME}")"; then
        fail "backup client cnf authentication failed"
    fi
    DB_ACCOUNT="${DB_ACCOUNT//$'\r'/}"
    [ -n "${DB_ACCOUNT}" ] && [[ "${DB_ACCOUNT}" != *$'\n'* ]] || fail "could not determine the authenticated database account"
    if ! docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 --batch --skip-column-names \
        -e 'SELECT 1 FROM django_migrations LIMIT 1' "${DB_NAME}" 2>"${RUNTIME_DIR}/db_select_test.err"; then
        local db_err; db_err="$(cat "${RUNTIME_DIR}/db_select_test.err" 2>/dev/null | head -1)"
        fail "SELECT on ${DB_NAME}.django_migrations failed (account=${DB_ACCOUNT}): ${db_err:-unknown error}"
    fi
    DB_VERSION="$(docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 --batch --skip-column-names \
        -e 'SELECT VERSION()' "${DB_NAME}")"
    DB_VERSION="${DB_VERSION//$'\r'/}"
    log "Database credential check passed (account=${DB_ACCOUNT}, version=${DB_VERSION})"
}

backup_database_logical() {
    CURRENT_STAGE="database_dump"
    local dump_bin
    [ -n "${CONTAINER_CNF}" ] || prepare_database_credentials
    dump_bin="$(docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb-dump || command -v mysqldump')"
    [ -n "${dump_bin}" ] || fail "mariadb-dump/mysqldump is unavailable"
    log "Creating consistent logical dump as ${DB_ACCOUNT}"
    DUMP_FILE="${RUNTIME_DIR}/database.sql.gz"
    if ! docker exec "${DB_CONTAINER}" "${dump_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 \
        --single-transaction --routines --triggers --events --quick --hex-blob \
        --default-character-set=utf8mb4 --set-charset --skip-lock-tables \
        "${DB_NAME}" 2>"${RUNTIME_DIR}/database.stderr.log" | gzip -c > "${DUMP_FILE}"; then
        fail "mariadb-dump failed; see database.stderr.log"
    fi
    [ -s "${DUMP_FILE}" ] || fail "database dump is empty"
    gzip -t "${DUMP_FILE}" || fail "database dump gzip validation failed"
    zgrep -q -E '(^|[[:space:]])CREATE TABLE|Table structure for table' "${DUMP_FILE}" || \
        fail "database dump does not contain expected table structure"
    rm -f -- "${RUNTIME_DIR}/database.stderr.log"
    # dump 完成，清理容器内 cnf
    docker exec "${DB_CONTAINER}" rm -f -- "${CONTAINER_CNF}" >/dev/null
    CONTAINER_CNF=""
}

# ============================================
# binlog 归档
# 在 dump 之后执行：记录 binlog 位点 -> FLUSH BINARY LOGS 轮转 -> 复制已完成文件
# 应用已冻结（无新写入），位点在 dump 前后一致
# ============================================
archive_binlog() {
    CURRENT_STAGE="archive_binlog"
    local client_bin mysql_data_mp master_status
    [ -n "${CONTAINER_CNF}" ] || prepare_database_credentials
    client_bin="$(docker exec "${DB_CONTAINER}" sh -c 'command -v mariadb || command -v mysql')"

    # 1. 记录当前 binlog 位点（应用已冻结，此位点 = dump 一致性快照的位点）
    master_status="$(docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 --batch --skip-column-names \
        -e "SHOW MASTER STATUS" "${DB_NAME}")"
    BINLOG_FILE="$(echo "${master_status}" | head -1 | awk '{print $1}')"
    BINLOG_POS="$(echo "${master_status}" | head -1 | awk '{print $2}')"
    [ -n "${BINLOG_FILE}" ] || fail "could not determine current binlog file (is binary log enabled?)"
    log "Binlog position: ${BINLOG_FILE}:${BINLOG_POS}"

    # 2. FLUSH BINARY LOGS - 关闭当前 binlog 文件（可安全复制），打开新文件
    docker exec "${DB_CONTAINER}" "${client_bin}" \
        --defaults-extra-file="${CONTAINER_CNF}" \
        --host=127.0.0.1 --port=3306 \
        -e "FLUSH BINARY LOGS" 2>/dev/null
    log "Binary logs flushed; active file rotated"

    # 3. 定位 MySQL 数据卷在宿主机的挂载点
    mysql_data_mp="$(docker volume inspect -f '{{.Mountpoint}}' "${MYSQL_DATA_VOLUME}" 2>/dev/null || true)"
    [ -n "${mysql_data_mp}" ] && [ -d "${mysql_data_mp}" ] || \
        fail "MySQL data volume mountpoint not found: ${MYSQL_DATA_VOLUME}"

    # 4. 复制所有 binlog 文件（FLUSH 后当前活跃文件已变为已完成文件）
    BINLOG_DIR="${RUNTIME_DIR}/binlog"
    mkdir -p "${BINLOG_DIR}"
    local count=0
    for f in "${mysql_data_mp}"/mysql-bin.[0-9]*; do
        [ -f "$f" ] || continue
        local fname; fname="$(basename "$f")"
        cp -a "$f" "${BINLOG_DIR}/"
        log "  archived: ${fname} ($(du -h "$f" | cut -f1))"
        count=$((count + 1))
    done
    # binlog 索引文件
    [ -f "${mysql_data_mp}/mysql-bin.index" ] && \
        cp -a "${mysql_data_mp}/mysql-bin.index" "${BINLOG_DIR}/"

    if [ "${count}" -eq 0 ]; then
        log "No binlog files found to archive"
    else
        log "Archived ${count} binlog file(s) to staging"
    fi

    # 5. 清理容器内 cnf
    docker exec "${DB_CONTAINER}" rm -f -- "${CONTAINER_CNF}" >/dev/null
    CONTAINER_CNF=""
}

# ============================================
# 根 manifest
# ============================================
build_manifest() {
    CURRENT_STAGE="manifest"
    local git_commit binlog_count
    git_commit="$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    binlog_count="$(ls "${BINLOG_DIR}" 2>/dev/null | grep -c '^mysql-bin\.' || echo 0)"
    MANIFEST_FILE="${RUNTIME_DIR}/manifest.json"
    python3 - "${MANIFEST_FILE}" "${BACKUP_SET_ID}" "${DB_NAME}" "${DB_VERSION}" \
        "${DB_ACCOUNT}" "${DOCS_MP}" "${MED_MP}" "${git_commit}" "${STARTED_AT}" \
        "${BINLOG_FILE}" "${BINLOG_POS}" "${binlog_count}" <<'PY'
import json, sys
out, bid, dbn, ver, acct, docs, med, commit, started, bf, bp, bc = sys.argv[1:13]
json.dump({
    "backup_set_id": bid, "schema": "borg-1",
    "database_name": dbn, "database_version": ver, "database_account": acct,
    "git_commit": commit, "started_at": started,
    "documents_mountpoint": docs, "media_mountpoint": med,
    "binlog_file": bf, "binlog_pos": bp, "binlog_files_archived": int(bc),
}, open(out, "w"), ensure_ascii=False, indent=2)
PY
}

# ============================================
# borg create（本地）+ check
# 直接吃 dump 文件 + documents/media volume mountpoint 原始目录树，享受块级去重
# BORG_PASSPHRASE 已通过环境变量传递，borg 自动用于加密 repo
# ============================================
borg_create_local() {
    CURRENT_STAGE="borg_create_local"
    log "Creating local borg archive: ${BORG_REPO}::${ARCHIVE_NAME}"
    borg create --stats --compression "${BORG_COMPRESSION}" \
        --exclude '*/__pycache__' \
        --exclude '*/.cache' \
        --exclude '*/logs' \
        --exclude '*/document_chunks' \
        "${BORG_REPO}::${ARCHIVE_NAME}" \
        "${DUMP_FILE}" \
        "${DOCS_MP}" \
        "${MED_MP}" \
        "${MANIFEST_FILE}" \
        ${BINLOG_DIR:+"${BINLOG_DIR}"}
    LOCAL_ARCHIVE_CREATED=1

    CURRENT_STAGE="borg_check_local"
    borg check --repository-only "${BORG_REPO}"
    borg list "${BORG_REPO}::${ARCHIVE_NAME}" >/dev/null
    LOCAL_ARCHIVE_VERIFIED=1
    log "Local archive created and verified"
}

# ============================================
# 本地保留策略（GFS）
# ============================================
borg_prune_local() {
    CURRENT_STAGE="prune_local"
    borg prune --list --stats "${BORG_REPO}" \
        --prefix 'tdyw-' \
        --keep-within="${PRUNE_KEEP_WITHIN}" \
        --keep-daily="${PRUNE_KEEP_DAILY}" \
        --keep-weekly="${PRUNE_KEEP_WEEKLY}" \
        --keep-monthly="${PRUNE_KEEP_MONTHLY}"
    log "Local prune completed"
}

# ============================================
# 本地空间回收（borg 1.2：prune 只标记删除，compact 才归还磁盘空间）
# 实际释放量用 repo 目录 du 前后差值记录，避免依赖 borg 版本的 --stats 支持
# ============================================
borg_compact_local() {
    CURRENT_STAGE="compact_local"
    local usage_before usage_after delta
    usage_before="$(repo_disk_usage "${BORG_REPO}")"
    borg compact "${BORG_REPO}"
    usage_after="$(repo_disk_usage "${BORG_REPO}")"
    if [ -n "${usage_before}" ] && [ -n "${usage_after}" ]; then
        delta=$((usage_before - usage_after))
        if [ "${delta}" -gt 0 ]; then
            log "Local compact completed: reclaimed $(human_bytes "${delta}"), repo now $(human_bytes "${usage_after}")"
        else
            log "Local compact completed: no space reclaimed, repo now $(human_bytes "${usage_after}")"
        fi
    else
        log "Local compact completed"
    fi
}

# ============================================
# 推送远程仓库（PUSH_REMOTE=YES 时执行）
# 在 restore_application 之前执行：本地和远程 archive 都落盘并校验后才解冻恢复应用；
# 卷仍处冻结状态，远程 archive 与本地来自同一停写窗口，数据一致。
# 停机窗口只含 create + borg list 校验；远程 prune/compact 在恢复后的 borg_prune_remote 执行。
# 远程机需先独立 borg init repo + 配 SSH 免密
# ============================================
borg_push_remote() {
    is_yes "${PUSH_REMOTE}" || { log "Remote push skipped (PUSH_REMOTE=${PUSH_REMOTE})"; return 0; }
    CURRENT_STAGE="borg_create_remote"
    log "Creating remote borg archive: ${BORG_REMOTE_REPO}::${ARCHIVE_NAME}"
    BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" BORG_RSH="${BORG_RSH}" \
        borg create --stats --compression "${BORG_COMPRESSION}" \
        --exclude '*/__pycache__' \
        --exclude '*/.cache' \
        --exclude '*/logs' \
        --exclude '*/document_chunks' \
        "${BORG_REMOTE_REPO}::${ARCHIVE_NAME}" \
        "${DUMP_FILE}" \
        "${DOCS_MP}" \
        "${MED_MP}" \
        "${MANIFEST_FILE}" \
        ${BINLOG_DIR:+"${BINLOG_DIR}"}
    REMOTE_ARCHIVE_CREATED=1

    CURRENT_STAGE="borg_check_remote"
    BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" BORG_RSH="${BORG_RSH}" \
        borg list "${BORG_REMOTE_REPO}::${ARCHIVE_NAME}" >/dev/null
    REMOTE_ARCHIVE_VERIFIED=1
    log "Remote archive created and verified"
}

# ============================================
# 远程仓库清理（prune + compact，恢复后执行，不占停机窗口）
# ============================================
borg_prune_remote() {
    is_yes "${PUSH_REMOTE}" || return 0
    CURRENT_STAGE="prune_remote"
    BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" BORG_RSH="${BORG_RSH}" \
        borg prune --list --stats "${BORG_REMOTE_REPO}" \
        --prefix 'tdyw-' \
        --keep-within="${REMOTE_PRUNE_KEEP_WITHIN}" \
        --keep-daily="${REMOTE_PRUNE_KEEP_DAILY}" \
        --keep-weekly="${REMOTE_PRUNE_KEEP_WEEKLY}" \
        --keep-monthly="${REMOTE_PRUNE_KEEP_MONTHLY}"

    CURRENT_STAGE="compact_remote"
    BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" BORG_RSH="${BORG_RSH}" \
        borg compact "${BORG_REMOTE_REPO}"
    log "Remote repo pruned and compacted"
}

# ============================================
# 主流程
# ============================================
usage() {
    sed -n '3,60p' "${BASH_SOURCE[0]}"
}

main() {
    case "${1:-}" in
        --help|-h) usage; exit 0 ;;
        "") ;;
        *) fail "unknown argument: $1 (use --help)" ;;
    esac

    preflight
    check_disk_space
    print_plan

    if is_yes "${DRY_RUN}"; then
        log "DRY_RUN complete: no lock, service stop, or archive created"
        return 0
    fi

    acquire_maintenance_lock
    initialize_workdir
    freeze_application
    backup_database_logical
    archive_binlog
    build_manifest
    borg_create_local
    borg_push_remote

    FREEZE_SECONDS=$(($(date +%s) - FREEZE_STARTED_EPOCH))
    CURRENT_STAGE="restore_application"
    restore_application
    log "Write freeze duration: ${FREEZE_SECONDS}s"

    borg_prune_local
    borg_compact_local
    borg_prune_remote

    log "Borg backup published: ${BORG_REPO}::${ARCHIVE_NAME}"
    if is_yes "${PUSH_REMOTE}"; then
        log "Remote backup published: ${BORG_REMOTE_REPO}::${ARCHIVE_NAME}"
    fi
}

main "$@"
