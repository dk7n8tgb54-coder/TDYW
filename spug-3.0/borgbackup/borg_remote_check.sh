#!/usr/bin/env bash
# ================================================================================
# TDYW 远程 borg 仓库定期自检（部署在远程机本地执行，cron 调度）
# --------------------------------------------------------------------------------
# 背景：备份脚本推送远程后只做 borg list 快速校验（确认当次 archive 可读）；
#       仓库结构、archive 元数据、数据块的深度校验由本脚本定期执行，
#       在远程机本地运行（不经 SSH），不占备份停机窗口。
#
# 模式（第一个参数）：
#   repo（默认）  borg check --repository-only --max-duration=N
#                 仓库结构/段文件检查；限时 MAX_DURATION 秒，超时即中断，
#                 下次从断点继续（borg 在仓库内记录部分检查进度）。
#                 注意：部分检查只做段文件条目 CRC，弱于完整仓库检查。
#   archives      borg check --archives-only
#                 校验 manifest/元数据及文件分块引用是否齐全（不读数据块内容）。
#   data          borg check --verify-data
#                 解密并校验全部数据块内容，等于整仓读一遍，耗时最长且不限时；
#                 与 --repository-only 互斥（borg 1.2 语义），建议每月一次。
#
# 安全约定：
#   - 本脚本永不使用 --repair：修复会改动仓库，必须人工确认后手动执行。
#   - 只读检查持共享锁，可与 borg create 并行；远程 prune/compact 持排他锁，
#     撞上时最多等 LOCK_WAIT 秒后失败退出——属调度冲突，不是仓库损坏。
#     cron 时间请避开备份推送窗口（备份约 01:00 前后，含远程推送段）。
#
# 部署（远程机，如 tdywuser@172.16.40.2）：
#   mkdir -p /opt/borgbackup
#   cp borg_remote_check.sh /opt/borgbackup/ && chmod +x /opt/borgbackup/borg_remote_check.sh
#   cp borg_remote_check.env.example /opt/borgbackup/borg_remote_check.env
#   vi /opt/borgbackup/borg_remote_check.env    # 填 BORG_REPO / BORG_PASSPHRASE
#   chmod 600 /opt/borgbackup/borg_remote_check.env
#   /opt/borgbackup/borg_remote_check.sh repo   # 手动验证一次，看日志输出 PASS
#
# crontab -e 示例（需能读 env 文件的用户）：
#   # 每周日 04:30 仓库结构检查（限时 30 分钟，可断点续查）
#   30 4 * * 0 /opt/borgbackup/borg_remote_check.sh repo
#   # 每月 1 日 20:00 archive 元数据检查
#   0 20 1 * * /opt/borgbackup/borg_remote_check.sh archives
#   # 每月 15 日 20:00 全量数据块校验（耗时长，给次日 01:00 备份留余量）
#   0 20 15 * * /opt/borgbackup/borg_remote_check.sh data
#
# 主要环境变量（可在 crontab 行内覆盖）：
#   BORG_ENV_FILE   env 文件，默认 /opt/borgbackup/borg_remote_check.env（须 0600/0400）
#   MAX_DURATION    repo 模式限时秒数，默认 1800
#   LOCK_WAIT       等仓库锁最长秒数，默认 300
#   LOG_FILE        日志文件，默认脚本同目录 borg_remote_check.log，保留最近 5000 行
# ================================================================================

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BORG_ENV_FILE="${BORG_ENV_FILE:-/opt/borgbackup/borg_remote_check.env}"
MAX_DURATION="${MAX_DURATION:-1800}"
LOCK_WAIT="${LOCK_WAIT:-300}"
LOG_FILE="${LOG_FILE:-${SCRIPT_DIR}/borg_remote_check.log}"
LOG_KEEP_LINES="${LOG_KEEP_LINES:-5000}"
LOCK_FILE="${LOCK_FILE:-${SCRIPT_DIR}/.borg_remote_check.lock}"
MODE="${1:-repo}"

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${LOG_FILE}" >&2; }
fail() { log "ERROR: $*"; exit 1; }
usage() { sed -n '3,55p' "${BASH_SOURCE[0]}" >&2; }

load_env() {
    if [ -f "${BORG_ENV_FILE}" ]; then
        local mode; mode="$(stat -c '%a' "${BORG_ENV_FILE}" 2>/dev/null || true)"
        case "${mode}" in 600|400) ;; *) fail "env file must have mode 0600 or 0400: ${BORG_ENV_FILE}" ;; esac
        # shellcheck disable=SC1090
        set -a; . "${BORG_ENV_FILE}"; set +a
    fi
    [ -n "${BORG_REPO:-}" ] || fail "BORG_REPO is empty (set it in ${BORG_ENV_FILE})"
    [ -n "${BORG_PASSPHRASE:-}" ] || fail "BORG_PASSPHRASE is empty (set it in ${BORG_ENV_FILE})"
    export BORG_REPO BORG_PASSPHRASE
}

trim_log() {
    [ -f "${LOG_FILE}" ] || return 0
    tail -n "${LOG_KEEP_LINES}" "${LOG_FILE}" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "${LOG_FILE}" || true
}

run_check() {
    local started rc=0 duration
    case "${MODE}" in
        repo)
            log "mode=repo: borg check --repository-only --max-duration=${MAX_DURATION} (partial, resumable)"
            started=$(date +%s)
            borg --lock-wait="${LOCK_WAIT}" check --repository-only \
                --max-duration="${MAX_DURATION}" "${BORG_REPO}" >> "${LOG_FILE}" 2>&1 || rc=$?
            ;;
        archives)
            log "mode=archives: borg check --archives-only"
            started=$(date +%s)
            borg --lock-wait="${LOCK_WAIT}" check --archives-only "${BORG_REPO}" >> "${LOG_FILE}" 2>&1 || rc=$?
            ;;
        data)
            log "mode=data: borg check --verify-data (full data read, NOT time-limited)"
            started=$(date +%s)
            borg --lock-wait="${LOCK_WAIT}" check --verify-data "${BORG_REPO}" >> "${LOG_FILE}" 2>&1 || rc=$?
            ;;
        *) usage; fail "unknown mode: ${MODE} (use repo|archives|data)" ;;
    esac
    duration=$(( $(date +%s) - started ))
    if [ "${rc}" -eq 0 ]; then
        log "PASS mode=${MODE} duration=${duration}s repo=${BORG_REPO}"
    else
        log "FAIL mode=${MODE} rc=${rc} duration=${duration}s repo=${BORG_REPO}"
        log "hint: rc=2 通常为完整性问题；日志若出现 lock 相关报错则是与备份/维护撞锁（调度问题，非仓库损坏）"
        exit "${rc}"
    fi
}

main() {
    case "${MODE}" in --help|-h) usage; exit 0 ;; esac
    mkdir -p -- "$(dirname "${LOG_FILE}")" 2>/dev/null || true
    exec 8>"${LOCK_FILE}" 2>/dev/null || fail "cannot open lock file: ${LOCK_FILE}"
    flock -n 8 || fail "another remote check is already running"
    load_env
    log "=== borg remote check start: $(borg --version 2>/dev/null | head -1) host=$(hostname) ==="
    run_check
    trim_log
}

main
