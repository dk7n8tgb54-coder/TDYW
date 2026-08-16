#!/usr/bin/env bash
# ================================================================================
# TDYW 开发机恢复：把生产 borg 快照的提取目录恢复到本机（WSL Docker）tdyw 栈
# --------------------------------------------------------------------------------
# 输入：borg extract 手工提取的快照目录（如 restore_0816），结构：
#   tmp/tdyw-borg.*/{database.sql.gz, manifest.json, binlog/}
#   data/docker/volumes/docker_tdyw-documents/_data/
#   data/docker/volumes/docker_tdyw-media/_data/
#
# 动作（destructive，默认需输入 RESTORE_DEV 确认）：
#   1. 停 tdyw 应用容器（tdyw-db 保持运行）
#   2. DROP/CREATE 目标库 → gunzip 流式导入 database.sql.gz → 校验表数量
#   3. 清空并替换 documents/media 两个 docker 卷（与快照逐条目比对）
#   4. 启动 tdyw → 健康检查 → manage.py migrate 对齐 dev 代码 schema
#
# 安全设计：
#   - DB 密码只进容器内 /tmp 临时 cnf（0600），不进 argv、不落日志，用完即删
#   - 容器内带变量的命令一律 heredoc 走 stdin（git bash→wsl.exe→docker 的
#     引号转义会吃掉 "$MYSQL_ROOT_PASSWORD"，命令行传参不可靠，已实测）
#   - 失败时应用保持停止并打印所处阶段；数据处于中间状态时重跑本脚本即可重来
#   - 只碰 tdyw / tdyw-db / documents / media 卷，不触碰 tdyw-test 栈
#   - document-chunks 卷不在生产备份内（备份时排除），本脚本不处理（见结尾提示）
#
# 用法（git bash 或 WSL 内均可，docker 命令自动探测）：
#   ./borgbackup/borg_restore_to_dev.sh --check /e/TDYW/spug-3.0/restore_0816   # 只校验+打印计划
#   ./borgbackup/borg_restore_to_dev.sh /e/TDYW/spug-3.0/restore_0816          # 确认后执行
#   ASSUME_YES=YES ./borgbackup/borg_restore_to_dev.sh /e/TDYW/spug-3.0/restore_0816
#
# 主要环境变量：
#   APP_CONTAINER     默认 tdyw
#   DB_CONTAINER      默认 tdyw-db
#   DB_NAME           默认取 manifest 的 database_name，无 manifest 时 tdyw
#   DOCUMENTS_VOLUME  默认 docker_tdyw-documents
#   MEDIA_VOLUME      默认 docker_tdyw-media
#   RUN_MIGRATE       默认 YES；NO 时跳过 manage.py migrate
#   HEALTH_TIMEOUT    启动后健康检查等待秒数，默认 180
#   APP_STOP_TIMEOUT  停容器等待秒数，默认 900
#   DOCKER_CMD        覆盖 docker 命令探测结果（如固定 "wsl docker"）
# ================================================================================

set -Eeuo pipefail
umask 077

# git bash(MSYS) 会把 /tmp/...、/mnt/e/... 这类 Unix 风格参数自动转换成 Windows 路径
# 再传给 wsl.exe，导致容器内 cnf 路径和 docker -v 挂载参数损坏（已实测：路径被改写成
# C:/Program Files/Git/tmp/...）。禁用转换；在 WSL/Linux bash 下这两个变量无副作用。
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

APP_CONTAINER="${APP_CONTAINER:-tdyw}"
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
DB_NAME="${DB_NAME:-}"
DOCUMENTS_VOLUME="${DOCUMENTS_VOLUME:-docker_tdyw-documents}"
MEDIA_VOLUME="${MEDIA_VOLUME:-docker_tdyw-media}"
RUN_MIGRATE="${RUN_MIGRATE:-YES}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
APP_STOP_TIMEOUT="${APP_STOP_TIMEOUT:-900}"
DOCKER_CMD="${DOCKER_CMD:-}"

SNAPSHOT_DIR=""
CHECK_ONLY=0
ASSUME_YES="${ASSUME_YES:-NO}"
DOCKER=""
APP_IMAGE=""
DUMP_FILE=""
DOCS_SRC=""
MED_SRC=""
MANIFEST_FILE=""
CONTAINER_CNF="/tmp/tdyw_dev_restore_$$.cnf"
APP_STOPPED_BY_SCRIPT=0
CURRENT_STAGE="preflight"
STARTED_AT="$(date '+%s')"

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }
is_yes() { case "${1^^}" in YES|TRUE|1) return 0 ;; *) return 1 ;; esac; }
usage() { sed -n '3,48p' "${BASH_SOURCE[0]}"; }

cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    set +e
    if [ "${rc}" -ne 0 ]; then
        log "FAILED at stage: ${CURRENT_STAGE} (exit=${rc})"
        if [ -n "${DOCKER}" ]; then
            ${DOCKER} exec "${DB_CONTAINER}" rm -f "${CONTAINER_CNF}" >/dev/null 2>&1
        fi
        if [ "${APP_STOPPED_BY_SCRIPT}" -eq 1 ]; then
            log "应用容器 ${APP_CONTAINER} 保持停止：数据处于中间状态，"
            log "  排查后可重跑本脚本完整重来，或确认无误后手动 docker start ${APP_CONTAINER}"
        fi
    fi
    exit "${rc}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# ============================================
# 参数解析
# ============================================
parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --check) CHECK_ONLY=1; shift ;;
            --yes)   ASSUME_YES=YES; shift ;;
            -h|--help) usage; exit 0 ;;
            -*) fail "unknown option: $1" ;;
            *)
                [ -z "${SNAPSHOT_DIR}" ] || fail "only one snapshot dir allowed"
                SNAPSHOT_DIR="$1"; shift ;;
        esac
    done
    [ -n "${SNAPSHOT_DIR}" ] || { usage >&2; fail "snapshot dir required"; }
    command -v cygpath >/dev/null 2>&1 && SNAPSHOT_DIR="$(cygpath -u "${SNAPSHOT_DIR}")"
    [ -d "${SNAPSHOT_DIR}" ] || fail "snapshot dir not found: ${SNAPSHOT_DIR}"
    SNAPSHOT_DIR="$(cd "${SNAPSHOT_DIR}" && pwd)"
}

# git bash 的 /e/... 转成 WSL 的 /mnt/e/...（docker -v 挂载用）；已是 /mnt/ 或 WSL 原生路径则原样
to_wsl_path() {
    local p="$1"
    case "${p}" in
        /mnt/*) printf '%s' "${p}" ;;
        /[a-zA-Z]/*) printf '/mnt/%s%s' "$(printf '%s' "${p:1:1}" | tr 'A-Z' 'a-z')" "${p:2}" ;;
        *) printf '%s' "${p}" ;;
    esac
}

# ============================================
# docker 命令探测：本机 docker 在 WSL 里，git bash 直连 npipe 会失败
# ============================================
detect_docker() {
    if [ -n "${DOCKER_CMD}" ]; then DOCKER="${DOCKER_CMD}"; return; fi
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        DOCKER="docker"
    else
        command -v wsl >/dev/null 2>&1 || fail "neither 'docker' nor 'wsl' available"
        DOCKER="wsl docker"
    fi
    ${DOCKER} version >/dev/null 2>&1 || fail "docker daemon unreachable via: ${DOCKER}"
    log "docker command: ${DOCKER}"
}

# ============================================
# 定位快照内容 + 前置校验
# ============================================
locate_snapshot() {
    CURRENT_STAGE="locate_snapshot"
    DUMP_FILE="$(find "${SNAPSHOT_DIR}" -type f -name 'database.sql.gz' 2>/dev/null | head -1)"
    [ -n "${DUMP_FILE}" ] || fail "database.sql.gz not found under ${SNAPSHOT_DIR}"
    DOCS_SRC="$(find "${SNAPSHOT_DIR}" -type d -path "*${DOCUMENTS_VOLUME}/_data" 2>/dev/null | head -1)"
    MED_SRC="$(find "${SNAPSHOT_DIR}" -type d -path "*${MEDIA_VOLUME}/_data" 2>/dev/null | head -1)"
    [ -n "${DOCS_SRC}" ] || fail "documents source not found (*${DOCUMENTS_VOLUME}/_data) under ${SNAPSHOT_DIR}"
    [ -n "${MED_SRC}" ] || fail "media source not found (*${MEDIA_VOLUME}/_data) under ${SNAPSHOT_DIR}"
    MANIFEST_FILE="$(find "${SNAPSHOT_DIR}" -type f -name 'manifest.json' 2>/dev/null | head -1 || true)"

    gzip -t "${DUMP_FILE}" || fail "database.sql.gz gzip integrity check failed"

    if [ -z "${DB_NAME}" ]; then
        DB_NAME="tdyw"
        if [ -n "${MANIFEST_FILE}" ]; then
            DB_NAME="$(sed -n 's/.*"database_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${MANIFEST_FILE}" | head -1)"
            [ -n "${DB_NAME}" ] || DB_NAME="tdyw"
        fi
    fi
}

# 容器内临时 cnf（0600），密码不进 argv；后续用 --defaults-extra-file 调 mariadb
prepare_container_cnf() {
    ${DOCKER} exec -i "${DB_CONTAINER}" bash -s <<INNER_EOF
set -e
umask 077
printf '[client]\nuser=root\npassword=%s\n' "\$MYSQL_ROOT_PASSWORD" > "${CONTAINER_CNF}"
chmod 600 "${CONTAINER_CNF}"
INNER_EOF
}

drop_container_cnf() {
    ${DOCKER} exec "${DB_CONTAINER}" rm -f "${CONTAINER_CNF}" >/dev/null 2>&1 || true
}

# 只读查询：目标库表数量
query_table_count() {
    ${DOCKER} exec -i "${DB_CONTAINER}" mariadb \
        --defaults-extra-file="${CONTAINER_CNF}" -h 127.0.0.1 \
        --batch --skip-column-names 2>/dev/null <<INNER_EOF
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}';
INNER_EOF
}

check_prerequisites() {
    CURRENT_STAGE="prerequisites"
    ${DOCKER} inspect "${APP_CONTAINER}" >/dev/null 2>&1 || fail "app container not found: ${APP_CONTAINER}"
    ${DOCKER} inspect "${DB_CONTAINER}" >/dev/null 2>&1 || fail "db container not found: ${DB_CONTAINER}"
    [ "$(${DOCKER} inspect -f '{{.State.Running}}' "${DB_CONTAINER}")" = "true" ] \
        || fail "db container is not running: ${DB_CONTAINER}"
    ${DOCKER} volume inspect "${DOCUMENTS_VOLUME}" >/dev/null 2>&1 || fail "volume not found: ${DOCUMENTS_VOLUME}"
    ${DOCKER} volume inspect "${MEDIA_VOLUME}" >/dev/null 2>&1 || fail "volume not found: ${MEDIA_VOLUME}"
    APP_IMAGE="$(${DOCKER} inspect "${APP_CONTAINER}" --format '{{.Config.Image}}')"
    [ -n "${APP_IMAGE}" ] || fail "could not determine app image (needed as local copy helper)"
    ${DOCKER} image inspect "${APP_IMAGE}" >/dev/null 2>&1 || fail "app image not available locally: ${APP_IMAGE}"

    prepare_container_cnf
    local old_tables
    old_tables="$(query_table_count || echo '?')"
    drop_container_cnf
    log "当前 ${DB_NAME} 库表数量: ${old_tables}（恢复后将被整库替换）"
}

print_plan() {
    echo "============================================================"
    echo " TDYW 开发机恢复计划"
    echo "============================================================"
    echo "  快照目录:      ${SNAPSHOT_DIR}"
    [ -n "${MANIFEST_FILE}" ] && echo "  manifest:      $(sed -n 's/.*"backup_set_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${MANIFEST_FILE}" | head -1)"
    echo "  dump 文件:     ${DUMP_FILE} ($(du -h "${DUMP_FILE}" | cut -f1))"
    echo "  目标库:        ${DB_CONTAINER} / ${DB_NAME}（DROP 后重建）"
    echo "  documents 卷:  ${DOCUMENTS_VOLUME}  <-  ${DOCS_SRC}"
    echo "  media 卷:      ${MEDIA_VOLUME}  <-  ${MED_SRC}"
    echo "  应用容器:      ${APP_CONTAINER}（镜像 ${APP_IMAGE} 兼作搬运容器）"
    echo "  migrate:       ${RUN_MIGRATE}"
    echo "============================================================"
}

confirm() {
    [ "${CHECK_ONLY}" -eq 1 ] && return 0
    is_yes "${ASSUME_YES}" && { log "ASSUME_YES=YES，跳过确认"; return 0; }
    [ -t 0 ] || fail "stdin 不是终端且未设 ASSUME_YES=YES，拒绝执行 destructive 恢复"
    echo "WARNING: 这将覆盖开发库 ${DB_NAME}、卷 ${DOCUMENTS_VOLUME} 和 ${MEDIA_VOLUME}，现有数据不可恢复！"
    printf '输入 RESTORE_DEV 确认继续: '
    local answer; read -r answer
    [ "${answer}" = "RESTORE_DEV" ] || { log "已取消"; exit 2; }
}

# ============================================
# 执行阶段
# ============================================
stop_app() {
    CURRENT_STAGE="stop_app"
    if [ "$(${DOCKER} inspect -f '{{.State.Running}}' "${APP_CONTAINER}")" = "true" ]; then
        log "停止应用容器 ${APP_CONTAINER}"
        ${DOCKER} stop -t "${APP_STOP_TIMEOUT}" "${APP_CONTAINER}" >/dev/null
        APP_STOPPED_BY_SCRIPT=1
    else
        log "应用容器 ${APP_CONTAINER} 本来就未运行"
    fi
}

restore_database() {
    CURRENT_STAGE="restore_database"
    prepare_container_cnf
    log "DROP + CREATE 数据库 ${DB_NAME}"
    ${DOCKER} exec -i "${DB_CONTAINER}" mariadb \
        --defaults-extra-file="${CONTAINER_CNF}" -h 127.0.0.1 <<INNER_EOF
DROP DATABASE IF EXISTS \`${DB_NAME}\`;
CREATE DATABASE \`${DB_NAME}\` DEFAULT CHARACTER SET utf8mb4;
INNER_EOF

    log "流式导入 dump（gunzip | mariadb ${DB_NAME}）"
    if ! gunzip -c "${DUMP_FILE}" | ${DOCKER} exec -i "${DB_CONTAINER}" \
        mariadb --defaults-extra-file="${CONTAINER_CNF}" -h 127.0.0.1 "${DB_NAME}"; then
        drop_container_cnf
        fail "数据库导入失败"
    fi

    local tables
    tables="$(query_table_count || echo 0)"
    drop_container_cnf
    [ "${tables}" -gt 0 ] 2>/dev/null || fail "导入后表数量异常: ${tables}"
    log "数据库恢复完成: ${DB_NAME}（${tables} 张表）"
}

restore_files() {
    CURRENT_STAGE="restore_files"
    local docs_wsl med_wsl
    docs_wsl="$(to_wsl_path "${DOCS_SRC}")"
    med_wsl="$(to_wsl_path "${MED_SRC}")"
    log "替换卷内容: ${DOCUMENTS_VOLUME} 和 ${MEDIA_VOLUME}"
    ${DOCKER} run --rm -i \
        -v "${docs_wsl}":/src-docs:ro \
        -v "${med_wsl}":/src-media:ro \
        -v "${DOCUMENTS_VOLUME}":/dst-docs \
        -v "${MEDIA_VOLUME}":/dst-media \
        --entrypoint bash "${APP_IMAGE}" -s <<'INNER_EOF'
set -e
for pair in docs media; do
    src="/src-${pair}"; dst="/dst-${pair}"
    src_n="$(find "${src}" -mindepth 1 | wc -l)"
    find "${dst}" -mindepth 1 -delete
    cp -a "${src}/." "${dst}/"
    dst_n="$(find "${dst}" -mindepth 1 | wc -l)"
    if [ "${src_n}" -ne "${dst_n}" ]; then
        echo "MISMATCH ${pair}: src=${src_n} dst=${dst_n}"
        exit 1
    fi
    echo "OK ${pair}: ${dst_n} entries"
done
INNER_EOF
    log "documents/media 卷替换完成（条目数与快照一致）"
}

start_app() {
    CURRENT_STAGE="start_app"
    log "启动应用容器 ${APP_CONTAINER}"
    ${DOCKER} start "${APP_CONTAINER}" >/dev/null
    APP_STOPPED_BY_SCRIPT=0
    local deadline=$((SECONDS + HEALTH_TIMEOUT)) running health
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        running="$(${DOCKER} inspect -f '{{.State.Running}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        health="$(${DOCKER} inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        if [ "${running}" = "true" ] && { [ "${health}" = "healthy" ] || [ "${health}" = "none" ]; }; then
            log "应用健康检查通过 (health=${health})"
            return 0
        fi
        sleep 3
    done
    fail "应用在 ${HEALTH_TIMEOUT}s 内未恢复健康"
}

run_migrate() {
    is_yes "${RUN_MIGRATE}" || { log "跳过 migrate（RUN_MIGRATE=${RUN_MIGRATE}）"; return 0; }
    CURRENT_STAGE="migrate"
    log "执行 manage.py migrate（对齐开发代码 schema，与生产一致时为空操作）"
    if ${DOCKER} exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api \
        "${APP_CONTAINER}" python manage.py migrate --noinput; then
        log "migrate 完成"
    else
        log "WARNING: migrate 失败（数据已恢复，但 schema 可能与开发代码不一致，请手动检查）"
    fi
}

main() {
    parse_args "$@"
    detect_docker
    locate_snapshot
    check_prerequisites
    print_plan
    confirm
    if [ "${CHECK_ONLY}" -eq 1 ]; then
        log "--check 完成：未做任何修改"
        exit 0
    fi
    stop_app
    restore_database
    restore_files
    start_app
    run_migrate
    log "恢复完成，总耗时 $(( $(date '+%s') - STARTED_AT ))s"
    log "提示1: 登录账号密码已是生产库中的账号"
    log "提示2: document-chunks 卷不在备份内且未被本脚本处理，若资料库向量检索异常需单独重建"
}

main "$@"
