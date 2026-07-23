#!/bin/bash
# ================================================================================
# 数据库账号初始化与最小权限授权脚本（第二阶段：非 root 化改造）
# --------------------------------------------------------------------------------
# 适用：MariaDB 10.8.2（生产镜像 registry.cn-hangzhou.aliyuncs.com/openspug/mariadb:10.8.2）
#
# 目标账号：
#   tdyw_app     Django 运行时（仅目标库 SELECT/INSERT/UPDATE/DELETE）
#   tdyw_migrate 发布迁移（目标库 DDL + DML，不注入长期应用）
#   tdyw_backup  mariadb-dump / mariabackup（只读 + 备份必需全局权限）
#   tdyw_monitor 健康检查（仅连接，无业务表权限）
#   tdyw_dba     日常 DBA 操作（目标库 DDL+DML + PROCESS/RELOAD/SHOW DATABASES，无账号管理）
#
# root 账号不在本脚本管理范围。root 仅用于初始化和灾难恢复，应封存于密码管理器。
#
# 安全约束：
#   1. 默认 DRY_RUN，只打印打码后的 SQL，不执行。真实执行需 DB_ACCOUNTS_CONFIRM=YES
#   2. 密码只能从 secret 文件读取（权限 <= 0640），不接受空/默认/硬编码密码
#   3. 不使用 GRANT ALL
#   4. 幂等：CREATE USER IF NOT EXISTS + ALTER USER + REVOKE(容错) + GRANT 精确权限
#   5. 重复执行不产生额外权限
#   6. 输出不打印密码/哈希/完整连接串
#   7. 不自动删除账号（撤销请用 revoke_db_accounts.sh，且不自动 DROP USER）
#
# 用法（DRY_RUN，默认）：
#   ./init_db_accounts.sh
#
# 用法（真实执行，仅在测试库或获得明确授权后）：
#   DB_ACCOUNTS_CONFIRM=YES ./init_db_accounts.sh
#
# 环境变量（全部可通过环境覆盖，推荐用 secret 文件）：
#   DB_HOST                       目标数据库主机（默认 127.0.0.1）
#   DB_PORT                       目标数据库端口（默认 3306）
#   DB_TARGET_NAME                目标业务库名（默认 tdyw，须与生产 MYSQL_DATABASE 一致）
#   MYSQL_ROOT_PASSWORD_FILE      root 密码 secret 文件路径（创建账号的引导账号）
#   TDYW_APP_PASSWORD_FILE        tdyw_app 密码文件
#   TDYW_MIGRATE_PASSWORD_FILE    tdyw_migrate 密码文件
#   TDYW_BACKUP_PASSWORD_FILE     tdyw_backup 密码文件
#   TDYW_MONITOR_PASSWORD_FILE    tdyw_monitor 密码文件
#   TDYW_DBA_PASSWORD_FILE        tdyw_dba 密码文件
#   DB_ACCOUNTS_CONFIRM           设为 YES 才真实执行，否则 DRY_RUN
#   DB_ACCOUNT_APP_HOST_LIMIT     tdyw_app 允许连接的 host 段（默认 %，生产建议收紧为 10.% 等内网段）
#   DB_ACCOUNT_MIGRATE_HOST_LIMIT tdyw_migrate host 限制（默认 %）
#   DB_ACCOUNT_BACKUP_HOST_LIMIT  tdyw_backup host 限制（默认 %）
#   DB_ACCOUNT_MONITOR_HOST_LIMIT tdyw_monitor host 限制（默认 %）
#   DB_ACCOUNT_DBA_HOST_LIMIT     tdyw_dba host 限制（默认 %，生产建议收紧为 DBA 工作站 IP）
#
# 退出码：0=成功（DRY_RUN 或真实执行均成功） 1=校验/执行失败 2=参数错误
# ================================================================================
set -euo pipefail

# ---------- 默认值 ----------
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_TARGET_NAME="${DB_TARGET_NAME:-tdyw}"
DB_ACCOUNTS_CONFIRM="${DB_ACCOUNTS_CONFIRM:-NO}"
APP_HOST="${DB_ACCOUNT_APP_HOST_LIMIT:-%}"
MIGRATE_HOST="${DB_ACCOUNT_MIGRATE_HOST_LIMIT:-%}"
BACKUP_HOST="${DB_ACCOUNT_BACKUP_HOST_LIMIT:-%}"
MONITOR_HOST="${DB_ACCOUNT_MONITOR_HOST_LIMIT:-%}"
DBA_HOST="${DB_ACCOUNT_DBA_HOST_LIMIT:-%}"

# 账号清单（顺序固定，便于核对）
ACCOUNTS=(tdyw_app tdyw_migrate tdyw_backup tdyw_monitor tdyw_dba)

# 被禁止的弱密码/默认密码（小写匹配）
FORBIDDEN_PASSWORDS="root admin password passwd mysql mariadb 123456 12345678 1234567890 tdyw spug admin888 admin123 default test qwerty letmein"

# 临时文件（0600，trap 清理）
SQL_TMPFILE=""
ROOT_CNFFILE=""
declare -a TMPFILES=()

# ---------- 日志 ----------
log()     { printf '[%s] [INFO] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_ok()   { printf '[%s] [OK]   %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_warn() { printf '[%s] [WARN] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_err()  { printf '[%s] [ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }

# ---------- 清理 ----------
cleanup() {
    for f in "${TMPFILES[@]:-}"; do
        [ -n "$f" ] && [ -f "$f" ] && rm -f "$f" 2>/dev/null || true
    done
    # 清理容器内临时文件（docker 模式）
    [ -n "${CONTAINER_CNFS:-}" ] && cleanup_container_cnf 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ---------- secret 文件读取与校验 ----------
# 校验文件权限：必须 <= 0640（owner rw，group r，other 无）
check_secret_file() {
    local file="$1" label="$2"
    if [ -z "$file" ]; then
        log_err "${label}: 未指定 secret 文件路径（环境变量 ${label}_FILE）"
        return 1
    fi
    if [ ! -f "$file" ]; then
        log_err "${label}: secret 文件不存在: ${file}"
        return 1
    fi
    if [ ! -r "$file" ]; then
        log_err "${label}: secret 文件不可读: ${file}"
        return 1
    fi
    # 权限校验（符号链接取目标）
    local perm
    perm=$(stat -c '%a' "$file" 2>/dev/null || stat -f '%A' "$file" 2>/dev/null | tr -d ' ' )
    case "$perm" in
        600|640|400) : ;;  # 允许
        *)
            log_err "${label}: secret 文件权限 ${perm} 过于宽松，要求 0600/0640/0400: ${file}"
            return 1
            ;;
    esac
    # 内容非空
    if [ ! -s "$file" ]; then
        log_err "${label}: secret 文件为空: ${file}"
        return 1
    fi
    # 拒绝多行（密码不应含换行）
    local lines
    lines=$(wc -l < "$file" | tr -d ' ')
    if [ "${lines:-0}" -gt 0 ]; then
        log_warn "${label}: secret 文件含换行符，将只取首行（建议去掉换行）"
    fi
    return 0
}

# 读取 secret（仅取首行，去除首尾空白，不回显）
read_secret() {
    local file="$1"
    head -n 1 "$file" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

# 校验密码强度
validate_password() {
    local pw="$1" label="$2"
    if [ -z "$pw" ]; then
        log_err "${label}: 密码为空（拒绝空密码）"
        return 1
    fi
    if [ "${#pw}" -lt 12 ]; then
        log_err "${label}: 密码长度 ${#pw} < 12（拒绝弱密码）"
        return 1
    fi
    local lower
    lower=$(printf '%s' "$pw" | tr '[:upper:]' '[:lower:]')
    for bad in $FORBIDDEN_PASSWORDS; do
        if [ "$lower" = "$bad" ]; then
            log_err "${label}: 密码命中禁用列表（${bad}），拒绝默认/弱密码"
            return 1
        fi
    done
    # 拒绝纯数字
    if printf '%s' "$pw" | grep -Eq '^[0-9]+$'; then
        log_err "${label}: 密码为纯数字，拒绝"
        return 1
    fi
    return 0
}

# ---------- 生成 SQL（含真实密码，写入 0600 临时文件）----------
# 参数：$1=账号 $2=host $3=密码
gen_create_alter_sql() {
    local user="$1" host="$2" pw="$3"
    # CREATE USER IF NOT EXISTS + ALTER USER 更新密码（幂等）
    # 注意：MariaDB 不支持 ALTER USER IF EXISTS，但 CREATE USER IF NOT EXISTS 保证存在
    printf "CREATE USER IF NOT EXISTS '%s'@'%s' IDENTIFIED BY '%s';\n" "$user" "$host" "$pw"
    printf "ALTER USER '%s'@'%s' IDENTIFIED BY '%s';\n" "$user" "$host" "$pw"
}

# 生成账号级 SQL（CREATE/ALTER + REVOKE清理 + GRANT 精确权限）
# 参数：账号名 host 密码
gen_account_sql() {
    local user="$1" host="$2" pw="$3"

    # 1. 创建/更新账号（幂等）
    gen_create_alter_sql "$user" "$host" "$pw"

    # 2. 幂等清理：REVOKE ALL（容错，账号无权限时会报错，用 || true 吞掉并加注释）
    #    MariaDB 语法：REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'u'@'h';
    #    不能用 GRANT ALL，自然也不该给 ALL；这里先撤干净再授予精确权限
    printf "REVOKE ALL PRIVILEGES, GRANT OPTION FROM '%s'@'%s';\n" "$user" "$host"

    # 3. 按角色授予精确权限（绝不使用 GRANT ALL）
    case "$user" in
        tdyw_app)
            # 仅目标库 DML
            printf "GRANT SELECT, INSERT, UPDATE, DELETE ON \`%s\`.* TO '%s'@'%s';\n" \
                "$DB_TARGET_NAME" "$user" "$host"
            ;;
        tdyw_migrate)
            # 目标库 DDL + DML（发布迁移用，不注入长期应用）
            printf "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, CREATE TEMPORARY TABLES, LOCK TABLES ON \`%s\`.* TO '%s'@'%s';\n" \
                "$DB_TARGET_NAME" "$user" "$host"
            ;;
        tdyw_backup)
            # mariadb-dump 与 mariabackup 所需最小权限（MariaDB 10.8.2）
            # 全局：RELOAD(FLUSH/读general log)、PROCESS(查看线程)、LOCK TABLES、BINLOG MONITOR(mariabackup 读 binlog 位点)
            # 目标库：SELECT/SHOW VIEW/EVENT/TRIGGER（mariadb-dump 导出结构/数据）
            printf "GRANT RELOAD, PROCESS, LOCK TABLES, BINLOG MONITOR ON *.* TO '%s'@'%s';\n" "$user" "$host"
            printf "GRANT SELECT, SHOW VIEW, EVENT, TRIGGER ON \`%s\`.* TO '%s'@'%s';\n" \
                "$DB_TARGET_NAME" "$user" "$host"
            ;;
        tdyw_monitor)
            # 仅连接 + USAGE（健康检查 SELECT 1 / SHOW STATUS，information_schema 默认可访问）
            printf "GRANT USAGE ON *.* TO '%s'@'%s';\n" "$user" "$host"
            ;;
        tdyw_dba)
            # 日常 DBA 操作账号（替代 root 用于日常管理）
            # 目标库：全部 DML + DDL（建表、改表、查数据、改数据）
            # 全局：PROCESS（看线程）、RELOAD（FLUSH）、SHOW DATABASES
            # 不授予：FILE/SUPER/CREATE USER/GRANT OPTION/SHUTDOWN/REPLICATION
            # 严禁使用 GRANT ALL
            printf "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES, CREATE TEMPORARY TABLES, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE, EXECUTE ON \`%s\`.* TO '%s'@'%s';\n" \
                "$DB_TARGET_NAME" "$user" "$host"
            printf "GRANT PROCESS, RELOAD, SHOW DATABASES ON *.* TO '%s'@'%s';\n" "$user" "$host"
            ;;
        *)
            log_err "未知账号: $user"
            return 1
            ;;
    esac
    # 强制要求 TLS？生产可加 REQUIRE SSL，本阶段不强加（避免破坏现有无 TLS 内网）
    return 0
}

# 打码 SQL（用于 DRY_RUN 打印，隐藏密码）
redact_sql() {
    sed -E "s/IDENTIFIED BY '[^']*'/IDENTIFIED BY '***REDACTED***'/g"
}

# 执行 mysql 命令（根据 DB_EXEC_MODE 选择本地或 docker exec）
# 用法：run_mysql --defaults-extra-file=<cnf> [其他参数] < sql_file
# 或：  run_mysql --defaults-extra-file=<cnf> -N -e "SQL"
run_mysql() {
    if [ "$DB_EXEC_MODE" = "docker" ]; then
        # docker exec 模式：需要把 cnf 文件也复制进容器
        # 调用方需通过 MYSQL_LOCAL_CNF / MYSQL_CONTAINER_CNF 传递文件路径
        docker exec -i "$DB_CONTAINER" mysql "$@"
    else
        mysql "$@"
    fi
}

# 将本地 cnf 文件复制到容器内（docker 模式），返回容器内路径
# 用法：copy_cnf_to_container <local_path>
# 注意：用 docker exec + stdin 方式写入，避免 docker cp 的 CRLF 问题
copy_cnf_to_container() {
    local local_cnf="$1"
    local container_cnf="/tmp/init_db_accounts_$$.cnf"
    # 用 stdin 写入，确保 LF 换行
    docker exec -i "$DB_CONTAINER" bash -c "cat > '$container_cnf' && chmod 600 '$container_cnf'" < "$local_cnf"
    echo "$container_cnf"
}

# 执行后清理容器内临时文件
cleanup_container_cnf() {
    [ -n "${CONTAINER_CNFS:-}" ] || return 0
    for f in "${CONTAINER_CNFS[@]}"; do
        docker exec "$DB_CONTAINER" rm -f "$f" 2>/dev/null || true
    done
}

# ---------- 主流程 ----------
main() {
    log "============================================================"
    log "数据库账号初始化（最小权限改造，MariaDB 10.8.2）"
    log "目标库: ${DB_TARGET_NAME}  主机: ${DB_HOST}:${DB_PORT}"
    if [ "$DB_ACCOUNTS_CONFIRM" = "YES" ]; then
        log_warn "DB_ACCOUNTS_CONFIRM=YES，将真实执行（请确认目标为测试库或已获授权）"
    else
        log "DB_ACCOUNTS_CONFIRM=${DB_ACCOUNTS_CONFIRM} -> DRY_RUN 模式（仅打印打码 SQL，不执行）"
    fi
    log "============================================================"

    # mysql 客户端仅在真实执行时需要；DRY_RUN 不连接数据库
    # 支持两种执行方式：
    #   1. 本地 mysql 客户端（生产 Linux 直接装 mariadb-client）
    #   2. 通过 docker exec 在容器内执行（WSL/无 mysql 客户端环境）
    DB_EXEC_MODE="${DB_EXEC_MODE:-auto}"  # auto | local | docker
    DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"

    if [ "$DB_ACCOUNTS_CONFIRM" = "YES" ]; then
        if [ "$DB_EXEC_MODE" = "local" ]; then
            command -v mysql >/dev/null 2>&1 || { log_err "DB_EXEC_MODE=local 但本地无 mysql 客户端"; exit 1; }
        elif [ "$DB_EXEC_MODE" = "docker" ]; then
            command -v docker >/dev/null 2>&1 || { log_err "DB_EXEC_MODE=docker 但本地无 docker"; exit 1; }
            docker inspect "$DB_CONTAINER" >/dev/null 2>&1 || { log_err "容器 $DB_CONTAINER 不存在或未运行"; exit 1; }
        else  # auto
            if command -v mysql >/dev/null 2>&1; then
                DB_EXEC_MODE="local"
            elif command -v docker >/dev/null 2>&1 && docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
                DB_EXEC_MODE="docker"
                log_warn "本地无 mysql 客户端，改用 docker exec $DB_CONTAINER 执行"
            else
                log_err "真实执行需要 mysql 客户端或可用的 docker 容器 $DB_CONTAINER"
                log_err "请安装 mariadb-client，或设置 DB_EXEC_MODE=docker 通过容器执行"
                exit 1
            fi
        fi
    fi

    # 校验 root secret
    local root_pw_file="${MYSQL_ROOT_PASSWORD_FILE:-}"
    if ! check_secret_file "$root_pw_file" "MYSQL_ROOT_PASSWORD"; then
        log_err "缺少 root 密码 secret，无法创建账号（root 仅用于引导，创建后应用不再使用）"
        exit 2
    fi

    # 校验 5 个账号 secret
    declare -A PW_FILES=(
        [tdyw_app]="${TDYW_APP_PASSWORD_FILE:-}"
        [tdyw_migrate]="${TDYW_MIGRATE_PASSWORD_FILE:-}"
        [tdyw_backup]="${TDYW_BACKUP_PASSWORD_FILE:-}"
        [tdyw_monitor]="${TDYW_MONITOR_PASSWORD_FILE:-}"
        [tdyw_dba]="${TDYW_DBA_PASSWORD_FILE:-}"
    )
    declare -A HOSTS=(
        [tdyw_app]="$APP_HOST"
        [tdyw_migrate]="$MIGRATE_HOST"
        [tdyw_backup]="$BACKUP_HOST"
        [tdyw_monitor]="$MONITOR_HOST"
        [tdyw_dba]="$DBA_HOST"
    )

    for u in "${ACCOUNTS[@]}"; do
        if ! check_secret_file "${PW_FILES[$u]}" "${u^^}_PASSWORD"; then
            exit 2
        fi
    done

    # 读取并校验密码强度（不打印）
    declare -A PWS=()
    for u in "${ACCOUNTS[@]}"; do
        local pw
        pw=$(read_secret "${PW_FILES[$u]}")
        if ! validate_password "$pw" "$u"; then
            exit 2
        fi
        PWS[$u]="$pw"
    done

    # 读取 root 密码
    local root_pw
    root_pw=$(read_secret "$root_pw_file")

    # 生成完整 SQL 到临时文件
    SQL_TMPFILE=$(mktemp /tmp/db_accounts_init.XXXXXX.sql)
    chmod 600 "$SQL_TMPFILE"
    TMPFILES+=("$SQL_TMPFILE")

    {
        echo "-- 自动生成，请勿手动编辑。密码已隐藏于本 0600 临时文件，执行后立即删除。"
        echo "-- 生成时间: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "-- 目标库: ${DB_TARGET_NAME}"
        echo ""
        for u in "${ACCOUNTS[@]}"; do
            echo "-- ---------- ${u}@${HOSTS[$u]} ----------"
            gen_account_sql "$u" "${HOSTS[$u]}" "${PWS[$u]}"
            echo ""
        done
        echo "-- 刷新权限"
        echo "FLUSH PRIVILEGES;"
    } > "$SQL_TMPFILE"

    # ---------- DRY_RUN 展示 ----------
    log "---------- 将执行的 SQL（密码已打码） ----------"
    redact_sql < "$SQL_TMPFILE"
    log "---------- SQL 结束 ----------"

    if [ "$DB_ACCOUNTS_CONFIRM" != "YES" ]; then
        log_ok "DRY_RUN 完成。确认无误后设置 DB_ACCOUNTS_CONFIRM=YES 重新执行以应用。"
        log "提示：真实执行前请确认目标为独立测试数据库；生产执行需获得明确授权。"
        exit 0
    fi

    # ---------- 真实执行 ----------
    # docker 模式下，host 改为 127.0.0.1（容器内连接本机数据库）
    local exec_host="$DB_HOST"
    if [ "$DB_EXEC_MODE" = "docker" ]; then
        exec_host="127.0.0.1"
    fi
    # 生成 root 客户端配置文件（0600，避免密码进 argv）
    ROOT_CNFFILE=$(mktemp /tmp/db_accounts_root.XXXXXX.cnf)
    chmod 600 "$ROOT_CNFFILE"
    TMPFILES+=("$ROOT_CNFFILE")
    cat > "$ROOT_CNFFILE" <<EOF
[client]
host=${exec_host}
port=${DB_PORT}
user=root
password=${root_pw}
EOF
    # 确保 LF 换行（避免 Windows CRLF 导致 mysql 客户端报错）
    sed -i 's/\r$//' "$ROOT_CNFFILE" 2>/dev/null || true

    # docker 模式下，将 cnf 和 sql 文件复制到容器内
    CONTAINER_CNFS=()
    local exec_cnf="$ROOT_CNFFILE"
    local exec_sql="$SQL_TMPFILE"
    if [ "$DB_EXEC_MODE" = "docker" ]; then
        exec_cnf=$(copy_cnf_to_container "$ROOT_CNFFILE")
        CONTAINER_CNFS+=("$exec_cnf")
        # SQL 文件也用 stdin 方式写入容器（避免 CRLF）
        exec_sql="/tmp/init_db_accounts_sql_$$.sql"
        docker exec -i "$DB_CONTAINER" bash -c "cat > '$exec_sql' && chmod 600 '$exec_sql'" < "$SQL_TMPFILE"
        CONTAINER_CNFS+=("$exec_sql")
        log "（docker 模式）cnf 和 sql 已复制到容器 $DB_CONTAINER"
    fi

    log "正在连接 ${DB_HOST}:${DB_PORT} 并执行授权（模式: ${DB_EXEC_MODE}）..."
    if [ "$DB_EXEC_MODE" = "docker" ]; then
        # docker 模式：SQL 已在容器内，用 source 执行
        if docker exec "$DB_CONTAINER" mysql --defaults-extra-file="$exec_cnf" -e "source $exec_sql" 2>&1 | tee /tmp/db_accounts_exec.$$.log; then
            log_ok "账号初始化与授权执行完成"
        else
            log_err "执行失败（见上方输出）。注意：REVOKE 对无权限账号会报错，属正常幂等行为，但其他错误需排查。"
            cleanup_container_cnf
            exit 1
        fi
    else
        if mysql --defaults-extra-file="$exec_cnf" < "$SQL_TMPFILE" 2>&1 | tee /tmp/db_accounts_exec.$$.log; then
            log_ok "账号初始化与授权执行完成"
        else
            log_err "执行失败（见上方输出）。注意：REVOKE 对无权限账号会报错，属正常幂等行为，但其他错误需排查。"
            exit 1
        fi
    fi
    rm -f /tmp/db_accounts_exec.$$.log 2>/dev/null || true

    # ---------- 执行后核验（不打印密码） ----------
    log "---------- 执行后授权核验 ----------"
    for u in "${ACCOUNTS[@]}"; do
        log "账号: ${u}@${HOSTS[$u]}"
        if [ "$DB_EXEC_MODE" = "docker" ]; then
            docker exec -i "$DB_CONTAINER" mysql --defaults-extra-file="$exec_cnf" -N -e \
                "SHOW GRANTS FOR '${u}'@'${HOSTS[$u]}';" 2>/dev/null | \
                sed -E "s/IDENTIFIED BY '[^']*'/IDENTIFIED BY '***REDACTED***'/g" | sed 's/^/    /'
        else
            mysql --defaults-extra-file="$exec_cnf" -N -e \
                "SHOW GRANTS FOR '${u}'@'${HOSTS[$u]}';" 2>/dev/null | \
                sed -E "s/IDENTIFIED BY '[^']*'/IDENTIFIED BY '***REDACTED***'/g" | sed 's/^/    /'
        fi
    done

    cleanup_container_cnf

    log_ok "全部完成。请人工核对上方授权是否符合最小权限预期。"
    log "撤销多余权限请使用: revoke_db_accounts.sh（不自动删除账号）"
}

main "$@"
