#!/bin/bash
# ================================================================================
# 数据库账号权限撤销与禁用脚本（第二阶段配套）
# --------------------------------------------------------------------------------
# 用途：撤销 init_db_accounts.sh 授予的多余/全部权限，并可选锁定账号。
#
# 安全约束：
#   1. 默认 DRY_RUN。真实执行需 REVOKE_CONFIRM=YES
#   2. 不自动 DROP USER（删除账号需 DBA 手动执行，见末尾提示）
#   3. 不使用 GRANT ALL（撤销时用 REVOKE ALL PRIVILEGES, GRANT OPTION，这是撤销语义）
#   4. 默认仅撤销权限并锁定账号（ACCOUNT LOCK），保留账号本体便于审计
#
# 用法（DRY_RUN）：
#   ./revoke_db_accounts.sh                       # 撤销全部 4 个账号权限（保留账号+锁定）
#   REVOKE_MODE=app_only ./revoke_db_accounts.sh  # 仅撤销 tdyw_app
#
# 用法（真实执行）：
#   REVOKE_CONFIRM=YES ./revoke_db_accounts.sh
#
# 环境变量：
#   DB_HOST / DB_PORT / DB_TARGET_NAME            同 init_db_accounts.sh
#   MYSQL_ROOT_PASSWORD_FILE                       root secret 文件
#   REVOKE_MODE                                    all（默认）| app_only | dba_only
#   REVOKE_DROP                                    设为 YES 才允许 DROP USER（默认 NO，仅提示）
#   REVOKE_CONFIRM                                 YES 才真实执行
#   DB_ACCOUNT_APP_HOST_LIMIT 等                   host 段（同 init 脚本，默认 %）
# ================================================================================
set -euo pipefail

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_TARGET_NAME="${DB_TARGET_NAME:-tdyw}"
REVOKE_CONFIRM="${REVOKE_CONFIRM:-NO}"
REVOKE_MODE="${REVOKE_MODE:-all}"
REVOKE_DROP="${REVOKE_DROP:-NO}"
APP_HOST="${DB_ACCOUNT_APP_HOST_LIMIT:-%}"
MIGRATE_HOST="${DB_ACCOUNT_MIGRATE_HOST_LIMIT:-%}"
BACKUP_HOST="${DB_ACCOUNT_BACKUP_HOST_LIMIT:-%}"
MONITOR_HOST="${DB_ACCOUNT_MONITOR_HOST_LIMIT:-%}"
DBA_HOST="${DB_ACCOUNT_DBA_HOST_LIMIT:-%}"

declare -A HOSTS=(
    [tdyw_app]="$APP_HOST"
    [tdyw_migrate]="$MIGRATE_HOST"
    [tdyw_backup]="$BACKUP_HOST"
    [tdyw_monitor]="$MONITOR_HOST"
    [tdyw_dba]="$DBA_HOST"
)

if [ "$REVOKE_MODE" = "app_only" ]; then
    ACCOUNTS=(tdyw_app)
elif [ "$REVOKE_MODE" = "dba_only" ]; then
    ACCOUNTS=(tdyw_dba)
elif [ "$REVOKE_MODE" = "all" ]; then
    ACCOUNTS=(tdyw_app tdyw_migrate tdyw_backup tdyw_monitor tdyw_dba)
else
    echo "[ERROR] REVOKE_MODE 仅支持 all | app_only" >&2
    exit 2
fi

ROOT_CNFFILE=""
SQL_TMPFILE=""
TMPFILES=()

log()     { printf '[%s] [INFO] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_ok()   { printf '[%s] [OK]   %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_warn() { printf '[%s] [WARN] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_err()  { printf '[%s] [ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }

cleanup() {
    for f in "${TMPFILES[@]:-}"; do
        [ -n "$f" ] && [ -f "$f" ] && rm -f "$f" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

check_secret_file() {
    local file="$1" label="$2"
    [ -z "$file" ] && { log_err "${label}: 未指定 secret 文件"; return 1; }
    [ ! -f "$file" ] && { log_err "${label}: 文件不存在: ${file}"; return 1; }
    [ ! -r "$file" ] && { log_err "${label}: 文件不可读: ${file}"; return 1; }
    local perm
    perm=$(stat -c '%a' "$file" 2>/dev/null || stat -f '%A' "$file" 2>/dev/null | tr -d ' ')
    case "$perm" in 600|640|400) : ;; *) log_err "${label}: 权限 ${perm} 过宽"; return 1 ;; esac
    [ ! -s "$file" ] && { log_err "${label}: 文件为空"; return 1; }
    return 0
}

main() {
    log "============================================================"
    log "账号权限撤销（REVOKE_MODE=${REVOKE_MODE}）"
    if [ "$REVOKE_CONFIRM" = "YES" ]; then
        log_warn "REVOKE_CONFIRM=YES，将真实执行"
    else
        log "REVOKE_CONFIRM=${REVOKE_CONFIRM} -> DRY_RUN（仅打印 SQL，不执行）"
    fi
    log "============================================================"

    command -v mysql >/dev/null 2>&1 || { log_err "缺少 mysql 客户端"; exit 1; }

    local root_pw_file="${MYSQL_ROOT_PASSWORD_FILE:-}"
    check_secret_file "$root_pw_file" "MYSQL_ROOT_PASSWORD" || exit 2
    local root_pw
    root_pw=$(head -n 1 "$root_pw_file" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

    SQL_TMPFILE=$(mktemp /tmp/db_accounts_revoke.XXXXXX.sql)
    chmod 600 "$SQL_TMPFILE"
    TMPFILES+=("$SQL_TMPFILE")

    {
        echo "-- 撤销脚本生成时间: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "-- 注意：REVOKE ALL 对无权限账号会报错，属正常幂等行为"
        echo ""
        for u in "${ACCOUNTS[@]}"; do
            local host="${HOSTS[$u]}"
            echo "-- ---------- 撤销 ${u}@${host} ----------"
            # 撤销全部权限与授权选项（撤销语义，非授予）
            echo "REVOKE ALL PRIVILEGES, GRANT OPTION FROM '${u}'@'${host}';"
            # 锁定账号（MariaDB 10.4+），保留账号本体便于审计，不自动 DROP
            echo "ALTER USER '${u}'@'${host}' ACCOUNT LOCK;"
            echo ""
        done
        echo "FLUSH PRIVILEGES;"
    } > "$SQL_TMPFILE"

    log "---------- 将执行的 SQL ----------"
    cat "$SQL_TMPFILE"
    log "---------- SQL 结束 ----------"

    if [ "$REVOKE_CONFIRM" != "YES" ]; then
        log_ok "DRY_RUN 完成。确认后设置 REVOKE_CONFIRM=YES 执行。"
        log "提示：此脚本仅撤销权限并锁定账号，不会 DROP USER。"
        exit 0
    fi

    ROOT_CNFFILE=$(mktemp /tmp/db_accounts_root.XXXXXX.cnf)
    chmod 600 "$ROOT_CNFFILE"
    TMPFILES+=("$ROOT_CNFFILE")
    cat > "$ROOT_CNFFILE" <<EOF
[client]
host=${DB_HOST}
port=${DB_PORT}
user=root
password=${root_pw}
EOF

    log "正在执行撤销..."
    # REVOKE 对无权限账号会报错，用 || true 容许继续；但 ALTER/FLUSH 失败需捕获
    if ! mysql --defaults-extra-file="$ROOT_CNFFILE" --force < "$SQL_TMPFILE" 2>&1 | grep -v 'There is no such grant' ; then
        log_warn "执行过程中存在报错（部分 REVOKE 对无权限账号的报错已忽略）"
    fi
    log_ok "撤销执行完成"

    log "---------- 撤销后状态核验 ----------"
    for u in "${ACCOUNTS[@]}"; do
        local host="${HOSTS[$u]}"
        log "账号: ${u}@${host}"
        mysql --defaults-extra-file="$ROOT_CNFFILE" -N -e \
            "SHOW GRANTS FOR '${u}'@'${host}';" 2>/dev/null | \
            sed -E "s/IDENTIFIED BY '[^']*'/IDENTIFIED BY '***REDACTED***'/g" | sed 's/^/    /'
        # 账号锁定状态
        local locked
        locked=$(mysql --defaults-extra-file="$ROOT_CNFFILE" -N -e \
            "SELECT account_locked FROM mysql.user WHERE user='${u}' AND host='${host}';" 2>/dev/null || echo "?")
        log "    account_locked = ${locked}"
    done

    if [ "$REVOKE_DROP" = "YES" ]; then
        log_warn "REVOKE_DROP=YES，将删除账号本体（不可逆）"
        for u in "${ACCOUNTS[@]}"; do
            local host="${HOSTS[$u]}"
            log "DROP USER '${u}'@'${host}' ..."
            mysql --defaults-extra-file="$ROOT_CNFFILE" -e "DROP USER IF EXISTS '${u}'@'${host}';" || true
        done
    else
        log "提示：如需彻底删除账号（不可逆），手动执行："
        for u in "${ACCOUNTS[@]}"; do
            echo "  DROP USER IF EXISTS '${u}'@'${HOSTS[$u]}';"
        done
        log "或设置 REVOKE_DROP=YES 由脚本删除（仍需 REVOKE_CONFIRM=YES）。"
    fi
}

main "$@"
