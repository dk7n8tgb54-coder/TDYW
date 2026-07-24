#!/bin/bash
# DEPRECATED：新的 documents/media 增量由 backup_set_create.sh 统一生成，包含删除清单、
# 父链和目标快照校验。本脚本基于旧 marker，不能作为一致性生产备份入口。
# ================================================================================
# 资料库文件增量备份脚本（storage/documents）
# --------------------------------------------------------------------------------
# 基于 docker/docker-compose.yml 配置：
#   - 文件存储卷：tdyw-documents → 容器内 /data/spug/spug_api/storage/documents
#   - 容器名：tdyw-db 不相关，文件卷挂载在应用容器 tdyw 中
#     （脚本默认用 APP_CONTAINER=tdyw 访问）
#
# 目录结构（由 document_utils.py 生成）：
#   storage/documents/
#   ├── public/                    # 公共空间
#   │   └── folder-{id}/
#   │       ├── 原始名_时间戳_随机串.ext
#   │       └── thumbnails/
#   └── private/
#       └── user-{uid}/folder-{id}/...
#   注：document_chunks / document_merge_tasks 是上传临时数据，本脚本不备份。
#
# 增量策略：基于文件 mtime + ctime 的时间戳增量
#   - 首次运行：全量备份（扫描 documents 下所有实际文件）
#   - 后续运行：同时考虑 mtime 与 ctime 变化
#     · -newermt  捕获 mtime 变化（内容修改）
#     · -newerct  捕获 ctime 变化（复制/迁移/解压/还原等，即使 mtime 被保留也会被捕获）
#     说明：不使用 `find -cnewer <标记文件>`，因为标记文件通过 docker cp 进入容器时
#           其 ctime 会被重置为当前时间，导致 -cnewer 比较失效。改为以宿主机标记文件
#           的 mtime epoch 作为基准，通过 -newermt/-newerct 比较，时区无关且可靠。
#   - 标记文件：每次备份开始时记录起点，备份成功后才把正式 marker 更新为该起点，
#     避免漏掉备份过程中产生的文件变更。
#   - 资料库目录结构以数据库记录为准，物理目录只保存有文件的 folder-id 分桶；
#     空文件夹、只有子文件夹但自身无文件的父文件夹，可能没有对应物理目录，这是正常状态。
#     因此本脚本只备份实际文件，不单独备份空目录。
#
# 备份产物（每次成功备份生成最多 3 类文件）：
#   documents_(full|incr)_YYYYmmdd_HHMMSS.tar.gz    压缩归档
#   documents_(full|incr)_YYYYmmdd_HHMMSS.manifest  文件清单（TSV: 相对路径/大小/mtime/ctime）
#   documents_(full|incr)_YYYYmmdd_HHMMSS.meta      备份元信息（类型/时间/数量/容器/路径/基准时间）
#   说明：0 文件的增量备份不生成 tar.gz 与 manifest，但仍生成 meta 以便审计。
#
# 与 mariadb-dump / mariabackup 的关系：
#   数据库（全量） + 资料库文件（增量） 组成完整备份体系。恢复时先恢复数据库，
#   再解压文件备份到 storage/documents/。两者必须来自同一备份周期。
#
# 用法：
#   ./documents_incremental_backup.sh
#   ./documents_incremental_backup.sh full     # 强制全量备份
#
# 环境变量覆盖（可选）：
#   export BACKUP_DIR=/data/backups/documents       # 备份输出目录
#   export LOG_FILE=/var/log/documents_backup.log    # 日志文件
#   export KEEP_DAYS=90                               # 全量备份保留天数
#   export APP_CONTAINER=tdyw                        # 应用容器名（用于访问文件卷）
#
# 定时任务示例（crontab -e）：
#   # 每天 01:00 增量备份资料库文件
#   0 1 * * *   BACKUP_DIR=/data/backups/documents /path/to/documents_incremental_backup.sh
# ================================================================================

set -euo pipefail
umask 027

if [ "${ALLOW_LEGACY_STANDALONE_BACKUP:-NO}" != "YES" ]; then
    echo "ERROR: standalone documents backup is disabled; use backup_set_create.sh" >&2
    exit 64
fi

# ============================================
# 配置区
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/docker/.env}"

# 备份目录与日志
TDYW_BACKUP_ROOT="${TDYW_BACKUP_ROOT:-/data/backups/tdyw}"
TDYW_LOG_DIR="${TDYW_LOG_DIR:-/var/log/tdyw-backup}"
DEFAULT_BACKUP_DIR="${TDYW_BACKUP_ROOT}/documents"
DEFAULT_LOG_FILE="${TDYW_LOG_DIR}/documents_backup.log"
BACKUP_DIR="${BACKUP_DIR:-${DEFAULT_BACKUP_DIR}}"
LOG_FILE="${LOG_FILE:-${DEFAULT_LOG_FILE}}"

# 全量备份子目录 / 增量备份子目录
FULL_SUBDIR="${BACKUP_DIR}/full"
INCR_SUBDIR="${BACKUP_DIR}/incremental"
# 时间戳标记文件（记录上次备份时间，增量基准）
MARKER_FILE="${BACKUP_DIR}/.last_backup_marker"
RUN_MARKER_FILE=""

# 增量基准 epoch（宿主机标记文件的 mtime，供 find -newermt/-newerct 使用）
BASE_EPOCH=""

# 应用容器名：documents 卷挂载在应用容器（tdyw）上，不是 db 容器
APP_CONTAINER="${APP_CONTAINER:-tdyw}"

# 容器内文件存储路径
DOCUMENTS_PATH="${DOCUMENTS_PATH:-/data/spug/spug_api/storage/documents}"

# 保留策略（全量备份保留天数，增量备份随对应全量清理）
KEEP_DAYS="${KEEP_DAYS:-90}"
SKIP_CLEANUP="${SKIP_CLEANUP:-NO}"

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
# 前置检查
# ============================================
preflight() {
    log_info "前置检查..."

    if ! command -v docker >/dev/null 2>&1; then
        log_err "未找到 docker 命令"
        exit 1
    fi

    # 应用容器必须运行（文件卷挂在应用容器上）
    local state
    state="$(docker inspect -f '{{.State.Running}}' "${APP_CONTAINER}" 2>/dev/null || echo "false")"
    if [ "${state}" != "true" ]; then
        log_err "容器 ${APP_CONTAINER} 未运行"
        log_err "documents 卷挂载在应用容器上，请确认 APP_CONTAINER 配置正确"
        log_err "当前值: APP_CONTAINER=${APP_CONTAINER}"
        log_err "可用容器: docker ps --format '{{.Names}}'"
        exit 1
    fi
    log_ok "容器 ${APP_CONTAINER} 运行中"

    # 检查容器内 documents 目录是否存在
    if ! docker exec "${APP_CONTAINER}" test -d "${DOCUMENTS_PATH}" 2>/dev/null; then
        log_err "容器内目录不存在: ${DOCUMENTS_PATH}"
        log_err "请确认 documents 卷已正确挂载"
        exit 1
    fi
    log_ok "documents 目录存在: ${DOCUMENTS_PATH}"

    # 检查容器内 find 是否支持 -newermt/-newerct（GNU find 特性）
    if ! docker exec "${APP_CONTAINER}" find "${DOCUMENTS_PATH}" -maxdepth 0 -newermt "@0" 2>/dev/null >/dev/null; then
        log_err "容器内 find 不支持 -newermt，无法执行 mtime+ctime 增量备份"
        log_err "请确认容器内为 GNU findutils（busybox find 不支持）"
        exit 1
    fi

    # 创建备份目录
    mkdir -p "${FULL_SUBDIR}" "${INCR_SUBDIR}"
    touch "${LOG_FILE}"

    log_ok "前置检查通过"
}

# ============================================
# 标记文件处理
# ============================================
create_run_marker() {
    RUN_MARKER_FILE="$(mktemp)"
    touch "${RUN_MARKER_FILE}"
    log_info "本次备份起点已记录: ${RUN_MARKER_FILE}"
}

commit_run_marker() {
    if [ -z "${RUN_MARKER_FILE}" ] || [ ! -f "${RUN_MARKER_FILE}" ]; then
        log_err "本次备份起点标记不存在，拒绝更新增量基准"
        return 1
    fi

    cp -p "${RUN_MARKER_FILE}" "${MARKER_FILE}"
    rm -f "${RUN_MARKER_FILE}"
    RUN_MARKER_FILE=""
    log_ok "标记文件已更新为本次备份开始时间: ${MARKER_FILE}"
}

cleanup_run_marker() {
    if [ -n "${RUN_MARKER_FILE}" ] && [ -f "${RUN_MARKER_FILE}" ]; then
        rm -f "${RUN_MARKER_FILE}"
    fi
    RUN_MARKER_FILE=""
}

# ============================================
# 生成 manifest 文件（TSV: 相对路径 / 大小 / mtime(epoch) / ctime(epoch)）
# 参数: $1 = "full" 或 "incr", $2 = manifest 输出路径
# 增量模式依赖全局 BASE_EPOCH（宿主机标记文件 mtime epoch）
# 注意：manifest 按行存储，文件名含制表符或换行会破坏解析；本系统文件名经
#       document_utils.py 规范化（原始名_时间戳_随机串），实际不会出现此类字符。
# ============================================
generate_manifest() {
    local mode="$1"
    local manifest_file="$2"

    if [ "${mode}" = "full" ]; then
        # 全量：列出 documents 下所有文件的相对路径与元数据
        # find 遇到个别权限错误会返回非零，但不影响已扫描到的文件，因此不中止整体备份
        if ! docker exec "${APP_CONTAINER}" \
                find "${DOCUMENTS_PATH}" -type f \
                -printf '%P\t%s\t%T@\t%C@\n' 2>>"${LOG_FILE}" > "${manifest_file}"; then
            log_warn "find 扫描 documents 时遇到部分错误（可能是权限问题），已记录可访问文件"
        fi
    else
        # 增量：mtime 或 ctime 新于基准时间
        if [ -z "${BASE_EPOCH}" ]; then
            log_err "增量 manifest 生成失败：BASE_EPOCH 未设置"
            return 1
        fi
        if ! docker exec "${APP_CONTAINER}" \
                find "${DOCUMENTS_PATH}" -type f \
                \( -newermt "@${BASE_EPOCH}" -o -newerct "@${BASE_EPOCH}" \) \
                -printf '%P\t%s\t%T@\t%C@\n' 2>>"${LOG_FILE}" > "${manifest_file}"; then
            log_warn "find 增量扫描 documents 时遇到部分错误（可能是权限问题），已记录可访问文件"
        fi
    fi
}

# 从 manifest 派生 tar 文件列表（取第一列 = 相对路径）
manifest_to_list() {
    local manifest_file="$1"
    local list_file="$2"
    cut -f1 "${manifest_file}" > "${list_file}"
}

# ============================================
# 生成 meta 文件（记录本次备份元信息）
# 参数: $1=meta 路径 $2=backup_type $3=归档全路径(可空) $4=manifest 文件名(或 "-")
#       $5=文件数 $6=base_marker_time $7=started_at
# ============================================
write_meta() {
    local meta_file="$1" backup_type="$2" archive_path="$3" manifest_name="$4"
    local file_count="$5" base_marker_time="$6" started_at="$7"
    local finished_at archive_size="-" archive_name="-"

    finished_at="$(date '+%Y-%m-%d %H:%M:%S')"
    if [ -n "${archive_path}" ] && [ -f "${archive_path}" ]; then
        archive_size="$(du -h "${archive_path}" | cut -f1)"
        archive_name="$(basename "${archive_path}")"
    fi

    {
        echo "backup_type=${backup_type}"
        echo "backup_started_at=${started_at}"
        echo "backup_finished_at=${finished_at}"
        echo "app_container=${APP_CONTAINER}"
        echo "documents_path=${DOCUMENTS_PATH}"
        echo "file_count=${file_count}"
        echo "archive_name=${archive_name}"
        echo "archive_size=${archive_size}"
        echo "manifest_name=${manifest_name}"
        echo "base_marker_time=${base_marker_time}"
        echo "schema=manifest_tsv_v1:columns=relative_path,size,mtime_epoch,ctime_epoch"
    } > "${meta_file}"
    log_ok "meta 生成完成: ${meta_file}"
}

# ============================================
# 全量备份
# ============================================
backup_full() {
    log_info "========== 执行全量备份 =========="

    local ts name out_file manifest_file meta_file list_file count size
    ts="$(date +"%Y%m%d_%H%M%S")"
    name="documents_full_${ts}.tar.gz"
    out_file="${FULL_SUBDIR}/${name}"
    manifest_file="${FULL_SUBDIR}/documents_full_${ts}.manifest"
    meta_file="${FULL_SUBDIR}/documents_full_${ts}.meta"

    local started_at
    started_at="$(date '+%Y-%m-%d %H:%M:%S')"

    log_info "目标文件: ${out_file}"
    create_run_marker

    # 生成 manifest（全量：所有文件）
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    generate_manifest full "${manifest_tmp}"

    # 派生 tar 文件列表
    list_file="$(mktemp)"
    manifest_to_list "${manifest_tmp}" "${list_file}"
    count="$(wc -l < "${list_file}" | tr -d ' ')"
    log_info "待备份文件数: ${count}"

    if [ "${count}" -eq 0 ]; then
        log_warn "documents 目录为空，跳过全量归档，仅生成 meta"
        write_meta "${meta_file}" "full" "" "-" "0" "-" "${started_at}"
        rm -f "${list_file}" "${manifest_tmp}"
        commit_run_marker
        return 0
    fi

    # 把文件列表拷贝到容器，用 tar -T 打包（流式输出到宿主机）
    local container_list="/tmp/backup_filelist_${ts}.txt"
    docker cp "${list_file}" "${APP_CONTAINER}:${container_list}" 2>>"${LOG_FILE}"

    if ! docker exec "${APP_CONTAINER}" \
            tar czf - -C "${DOCUMENTS_PATH}" -T "${container_list}" 2>>"${LOG_FILE}" > "${out_file}"; then
        log_err "全量备份打包失败"
        rm -f "${out_file}"
        docker exec "${APP_CONTAINER}" rm -f "${container_list}" 2>/dev/null || true
        rm -f "${list_file}" "${manifest_tmp}"
        cleanup_run_marker
        return 1
    fi

    # 清理容器内临时文件列表
    docker exec "${APP_CONTAINER}" rm -f "${container_list}" 2>/dev/null || true
    rm -f "${list_file}"

    # 校验归档非空
    if [ ! -s "${out_file}" ]; then
        log_err "全量备份文件为空"
        rm -f "${out_file}" "${manifest_tmp}"
        cleanup_run_marker
        return 1
    fi

    # tar 完整性校验
    if ! tar tzf "${out_file}" >/dev/null 2>&1; then
        log_err "全量备份 tar.gz 校验失败，文件可能损坏: ${out_file}"
        rm -f "${out_file}" "${manifest_tmp}"
        cleanup_run_marker
        return 1
    fi

    # 保存 manifest
    mv -f "${manifest_tmp}" "${manifest_file}"

    size="$(du -h "${out_file}" | cut -f1)"
    log_ok "全量备份完成: ${name} (${size}, ${count} 个文件)"

    write_meta "${meta_file}" "full" "${out_file}" "$(basename "${manifest_file}")" "${count}" "-" "${started_at}"

    # 提交备份开始时的标记，避免漏掉备份过程中产生的文件变更
    commit_run_marker

    return 0
}

# ============================================
# 增量备份
# ============================================
backup_incremental() {
    log_info "========== 执行增量备份 =========="

    # 无标记文件 → 自动转全量
    if [ ! -f "${MARKER_FILE}" ]; then
        log_warn "未找到标记文件 ${MARKER_FILE}，本次自动转为全量备份"
        backup_full
        return $?
    fi

    local ts name out_file manifest_file meta_file list_file count size
    ts="$(date +"%Y%m%d_%H%M%S")"
    name="documents_incr_${ts}.tar.gz"
    out_file="${INCR_SUBDIR}/${name}"
    manifest_file="${INCR_SUBDIR}/documents_incr_${ts}.manifest"
    meta_file="${INCR_SUBDIR}/documents_incr_${ts}.meta"

    local started_at base_marker_human
    started_at="$(date '+%Y-%m-%d %H:%M:%S')"
    BASE_EPOCH="$(stat -c %Y "${MARKER_FILE}" 2>/dev/null || echo 0)"
    base_marker_human="$(stat -c %y "${MARKER_FILE}" 2>/dev/null | cut -d. -f1 || echo "-")"

    # 基准时间无法读取 → 退化为全量，避免漏备份
    if [ -z "${BASE_EPOCH}" ] || [ "${BASE_EPOCH}" = "0" ]; then
        log_warn "无法读取标记文件 mtime，退化为全量备份: ${MARKER_FILE}"
        backup_full
        return $?
    fi

    log_info "目标文件: ${out_file}"
    log_info "增量基准时间: ${base_marker_human} (epoch=${BASE_EPOCH})"
    create_run_marker

    # 生成增量 manifest（mtime 或 ctime 新于基准）
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    generate_manifest incr "${manifest_tmp}"

    # 派生 tar 文件列表
    list_file="$(mktemp)"
    manifest_to_list "${manifest_tmp}" "${list_file}"
    count="$(wc -l < "${list_file}" | tr -d ' ')"
    log_info "变动文件数: ${count}"

    if [ "${count}" -eq 0 ]; then
        log_ok "无变动文件，仅生成 meta（不生成归档与 manifest）"
        write_meta "${meta_file}" "incr" "" "-" "0" "${base_marker_human}" "${started_at}"
        rm -f "${list_file}" "${manifest_tmp}"
        commit_run_marker
        return 0
    fi

    # 打包增量文件
    local container_list="/tmp/backup_filelist_${ts}.txt"
    docker cp "${list_file}" "${APP_CONTAINER}:${container_list}" 2>>"${LOG_FILE}"

    if ! docker exec "${APP_CONTAINER}" \
            tar czf - -C "${DOCUMENTS_PATH}" -T "${container_list}" 2>>"${LOG_FILE}" > "${out_file}"; then
        log_err "增量备份打包失败"
        rm -f "${out_file}"
        docker exec "${APP_CONTAINER}" rm -f "${container_list}" 2>/dev/null || true
        rm -f "${list_file}" "${manifest_tmp}"
        cleanup_run_marker
        return 1
    fi

    docker exec "${APP_CONTAINER}" rm -f "${container_list}" 2>/dev/null || true
    rm -f "${list_file}"

    if [ ! -s "${out_file}" ]; then
        log_err "增量备份文件为空"
        rm -f "${out_file}" "${manifest_tmp}"
        cleanup_run_marker
        return 1
    fi

    if ! tar tzf "${out_file}" >/dev/null 2>&1; then
        log_err "增量备份 tar.gz 校验失败: ${out_file}"
        rm -f "${out_file}" "${manifest_tmp}"
        cleanup_run_marker
        return 1
    fi

    # 保存 manifest
    mv -f "${manifest_tmp}" "${manifest_file}"
    size="$(du -h "${out_file}" | cut -f1)"
    log_ok "增量备份完成: ${name} (${size}, ${count} 个文件)"

    write_meta "${meta_file}" "incr" "${out_file}" "$(basename "${manifest_file}")" "${count}" "${base_marker_human}" "${started_at}"

    # 提交备份开始时的标记，避免漏掉本次扫描后产生的文件变更
    commit_run_marker

    return 0
}

# ============================================
# 兼容旧调用：更新标记文件为当前时间
# ============================================
update_marker() {
    touch "${MARKER_FILE}"
    log_ok "标记文件已更新: ${MARKER_FILE}"
}

# ============================================
# 清理过期备份（同时清理配套的 manifest / meta）
# ============================================
cleanup() {
    local deleted_full=0 deleted_incr=0 f base

    # 清理过期的全量备份及其配套文件
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        base="${f%.tar.gz}"
        rm -f "$f" "${base}.manifest" "${base}.meta"
        deleted_full=$((deleted_full + 1))
    done < <(find "${FULL_SUBDIR}" -name "documents_full_*.tar.gz" -type f -mtime +"${KEEP_DAYS}" 2>/dev/null)

    # 清理过期的增量备份及其配套文件
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        base="${f%.tar.gz}"
        rm -f "$f" "${base}.manifest" "${base}.meta"
        deleted_incr=$((deleted_incr + 1))
    done < <(find "${INCR_SUBDIR}" -name "documents_incr_*.tar.gz" -type f -mtime +"${KEEP_DAYS}" 2>/dev/null)

    # 清理孤立的 manifest / meta（对应归档已不存在或同样过期）
    find "${FULL_SUBDIR}" -name "documents_full_*.manifest" -type f -mtime +"${KEEP_DAYS}" -delete 2>/dev/null || true
    find "${FULL_SUBDIR}" -name "documents_full_*.meta" -type f -mtime +"${KEEP_DAYS}" -delete 2>/dev/null || true
    find "${INCR_SUBDIR}" -name "documents_incr_*.manifest" -type f -mtime +"${KEEP_DAYS}" -delete 2>/dev/null || true
    find "${INCR_SUBDIR}" -name "documents_incr_*.meta" -type f -mtime +"${KEEP_DAYS}" -delete 2>/dev/null || true

    if [ "${deleted_full}" -gt 0 ]; then
        log_ok "清理过期全量备份: 删除 ${deleted_full} 个（>${KEEP_DAYS} 天，含 manifest/meta）"
    fi
    if [ "${deleted_incr}" -gt 0 ]; then
        log_ok "清理过期增量备份: 删除 ${deleted_incr} 个（>${KEEP_DAYS} 天，含 manifest/meta）"
    fi
    if [ "${deleted_full}" -eq 0 ] && [ "${deleted_incr}" -eq 0 ]; then
        log_info "无过期备份需清理"
    fi
}

# ============================================
# 备份摘要
# ============================================
summary() {
    log_info "========== 备份摘要 =========="
    log_info "全量备份目录: ${FULL_SUBDIR}"
    log_info "  最近 3 个全量备份:"
    ls -lht "${FULL_SUBDIR}"/documents_full_*.tar.gz 2>/dev/null | head -3 | \
        awk '{print "    " $9 " (" $5 ")"}' >> "${LOG_FILE}" 2>/dev/null || true
    log_info "增量备份目录: ${INCR_SUBDIR}"
    log_info "  最近 5 个增量备份:"
    ls -lht "${INCR_SUBDIR}"/documents_incr_*.tar.gz 2>/dev/null | head -5 | \
        awk '{print "    " $9 " (" $5 ")"}' >> "${LOG_FILE}" 2>/dev/null || true
    log_info "标记文件: ${MARKER_FILE}"
    log_info "每次备份均生成 .manifest（文件清单）与 .meta（元信息），用于还原后校验"
    log_info "磁盘占用:"
    du -sh "${BACKUP_DIR}" 2>/dev/null | awk '{print "    " $0}' >> "${LOG_FILE}" 2>/dev/null || true
    log_info "========== 备份完成 =========="
}

# ============================================
# 主流程
# ============================================
main() {
    local force_full="${1:-}"

    mkdir -p "$(dirname "${LOG_FILE}")"
    preflight

    log_info "########################################################"
    log_info "# 资料库文件增量备份任务开始"
    log_info "# 容器: ${APP_CONTAINER}  路径: ${DOCUMENTS_PATH}"
    log_info "# 增量策略: mtime + ctime（-newermt / -newerct）"
    log_info "########################################################"

    local rc=0

    if [ "${force_full}" = "full" ]; then
        log_info "模式: 强制全量备份"
        backup_full || rc=1
    elif [ ! -f "${MARKER_FILE}" ]; then
        log_info "模式: 首次备份（无标记文件）→ 自动全量"
        backup_full || rc=1
    else
        log_info "模式: 增量备份"
        backup_incremental || rc=1
    fi

    if [ "${SKIP_CLEANUP}" = "YES" ]; then
        log_info "SKIP_CLEANUP=YES，跳过子脚本文件级清理"
    else
        cleanup
    fi
    summary

    if [ "${rc}" -ne 0 ]; then
        log_err "备份失败，请检查日志: ${LOG_FILE}"
    fi

    exit "${rc}"
}

main "$@"
