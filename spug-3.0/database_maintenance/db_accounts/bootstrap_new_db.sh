#!/bin/bash
# ================================================================================
# 空白数据库一键 bootstrap（全新部署用，非首次请用 run_init.sh）
# --------------------------------------------------------------------------------
# 适用场景：全新的 MariaDB 实例，只有 root 能登录，tdyw 库尚未创建或为空。
#
# 本脚本依次执行：
#   1. 创建业务库（CREATE DATABASE IF NOT EXISTS，幂等）
#   2. 创建 5 个账号并授权（init_db_accounts.sh）
#   3. 生成 monitor.cnf / backup.cnf 客户端配置文件
#   4. 提示后续步骤（运行 migration、切换应用配置）
#
# 用法：
#   bash database_maintenance/db_accounts/bootstrap_new_db.sh              # DRY_RUN
#   DB_ACCOUNTS_CONFIRM=YES bash .../bootstrap_new_db.sh                    # 真实执行
#
# 环境变量（可选）：
#   DB_HOST / DB_PORT / DB_TARGET_NAME     数据库连接（默认 127.0.0.1:3306 / tdyw）
#   SECRETS_DIR                            secret 目录（默认 docker/secrets/）
#   DB_ACCOUNTS_CONFIRM=YES                 真实执行（默认 NO=DRY_RUN）
# ================================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SECRETS_DIR="${SECRETS_DIR:-${PROJECT_ROOT}/docker/secrets}"

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_TARGET_NAME="${DB_TARGET_NAME:-tdyw}"
DB_ACCOUNTS_CONFIRM="${DB_ACCOUNTS_CONFIRM:-NO}"

log()     { printf '[%s] [INFO] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_ok()   { printf '[%s] [OK]   %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_warn() { printf '[%s] [WARN] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_err()  { printf '[%s] [ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }

# ---------- 检查 secret 文件 ----------
ROOT_PW_FILE="${SECRETS_DIR}/root_password"
if [ ! -f "${ROOT_PW_FILE}" ]; then
    log_err "root 密码文件不存在: ${ROOT_PW_FILE}"
    log_err "请从 docker/.env 提取或重新生成"
    exit 2
fi

# 读取 root 密码
ROOT_PW=$(head -1 "${ROOT_PW_FILE}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

# 生成临时 root cnf 文件（0600）
ROOT_CNFFILE=$(mktemp /tmp/bootstrap_root.XXXXXX.cnf)
chmod 600 "$ROOT_CNFFILE"
cat > "$ROOT_CNFFILE" <<EOF
[client]
host=${DB_HOST}
port=${DB_PORT}
user=root
password=${ROOT_PW}
EOF
trap 'rm -f "$ROOT_CNFFILE"' EXIT

log "============================================================"
log "空白数据库 bootstrap（MariaDB 全新部署）"
log "目标库: ${DB_TARGET_NAME}  主机: ${DB_HOST}:${DB_PORT}"
if [ "$DB_ACCOUNTS_CONFIRM" = "YES" ]; then
    log_warn "DB_ACCOUNTS_CONFIRM=YES，将真实执行"
else
    log "DB_ACCOUNTS_CONFIRM=${DB_ACCOUNTS_CONFIRM} -> DRY_RUN 模式"
fi
log "============================================================"

# ---------- Step 1: 创建业务库 ----------
log "Step 1: 创建业务库 ${DB_TARGET_NAME}"

if [ "$DB_ACCOUNTS_CONFIRM" = "YES" ]; then
    if mysql --defaults-extra-file="$ROOT_CNFFILE" -e \
        "CREATE DATABASE IF NOT EXISTS \`${DB_TARGET_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"; then
        log_ok "业务库 ${DB_TARGET_NAME} 已就绪"
    else
        log_err "创建业务库失败"
        exit 1
    fi
else
    log "[DRY_RUN] 将执行: CREATE DATABASE IF NOT EXISTS \`${DB_TARGET_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
fi

# ---------- Step 2: 创建账号（调用 init_db_accounts.sh）----------
log "Step 2: 创建 5 个账号并授权"
log "  调用 init_db_accounts.sh ..."

# 通过 run_init.sh wrapper 自动读取 secret
if [ "$DB_ACCOUNTS_CONFIRM" = "YES" ]; then
    DB_ACCOUNTS_CONFIRM=YES bash "${SCRIPT_DIR}/run_init.sh"
    rc=$?
else
    bash "${SCRIPT_DIR}/run_init.sh"
    rc=$?
fi

if [ $rc -ne 0 ]; then
    log_err "账号创建失败（退出码 $rc）"
    exit $rc
fi
log_ok "账号创建完成"

# ---------- Step 3: 生成客户端配置文件 ----------
log "Step 3: 生成客户端配置文件"

generate_cnf() {
    local template="$1" output="$2" password_file="$3" user="$4"
    local password
    password=$(head -1 "${SECRETS_DIR}/${password_file}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

    if [ ! -f "${template}" ]; then
        log_warn "模板不存在: ${template}"
        return 0
    fi

    if [ "$DB_ACCOUNTS_CONFIRM" = "YES" ]; then
        # 从模板生成，替换 host/port/user/password
        sed -e "s/^host=.*/host=${DB_HOST}/" \
            -e "s/^port=.*/port=${DB_PORT}/" \
            -e "s/^user=.*/user=${user}/" \
            -e "s/^password=.*/password=${password}/" \
            "${template}" > "${output}"
        chmod 600 "${output}"
        log_ok "已生成: ${output}"
    else
        log "[DRY_RUN] 将生成: ${output}（从 ${template}）"
    fi
}

generate_cnf "${SCRIPT_DIR}/monitor_client.cnf.template" \
             "${SECRETS_DIR}/monitor.cnf" \
             "tdyw_monitor_password" "tdyw_monitor"

generate_cnf "${SCRIPT_DIR}/backup_client.cnf.template" \
             "${SECRETS_DIR}/tdyw_backup.cnf" \
             "tdyw_backup_password" "tdyw_backup"

generate_cnf "${SCRIPT_DIR}/dba_client.cnf.template" \
             "${SECRETS_DIR}/tdyw_dba.cnf" \
             "tdyw_dba_password" "tdyw_dba"

# ---------- Step 4: 后续步骤提示 ----------
log "============================================================"
log "Bootstrap 完成"
log "============================================================"
echo ""
echo "后续步骤："
echo ""
echo "1. 运行数据库 migration（使用 tdyw_migrate 账号）："
echo "   docker compose -f docker/docker-compose.yml run --rm tdyw-migrate"
echo ""
echo "2. 启动应用（使用 tdyw_app 账号）："
echo "   docker compose -f docker/docker-compose.yml up -d"
echo ""
echo "3. 验证发布配置："
echo "   docker exec -e PYTHONIOENCODING=utf-8 tdyw python /tmp/audit_config.py"
echo "   # 确认无 FAIL"
echo ""
echo "4. DBA 日常登录（使用 tdyw_dba 账号）："
echo "   mysql --defaults-extra-file=${SECRETS_DIR}/tdyw_dba.cnf"
echo ""
echo "5. 备份测试（使用 tdyw_backup 账号）："
echo "   BACKUP_CLIENT_CNF=${SECRETS_DIR}/tdyw_backup.cnf \\"
echo "   bash backups/mariadump_backup.sh"
echo ""
if [ "$DB_ACCOUNTS_CONFIRM" != "YES" ]; then
    log_warn "本次为 DRY_RUN，未实际执行。确认无误后："
    log_warn "  DB_ACCOUNTS_CONFIRM=YES bash ${SCRIPT_DIR}/bootstrap_new_db.sh"
fi
