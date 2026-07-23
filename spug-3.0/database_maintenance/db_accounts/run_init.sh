#!/bin/bash
# ================================================================================
# 账号初始化 wrapper（自动从 docker/secrets/ 读取密码文件，免去手写环境变量）
# --------------------------------------------------------------------------------
# 用法：
#   bash database_maintenance/db_accounts/run_init.sh              # DRY_RUN（默认）
#   DB_ACCOUNTS_CONFIRM=YES bash .../run_init.sh                    # 真实执行
#   DB_TARGET_NAME=mydb bash .../run_init.sh                        # 指定目标库名
#   DB_HOST=10.0.0.5 DB_PORT=3307 bash .../run_init.sh              # 指定数据库地址
#
# 前提：docker/secrets/ 下有以下文件（权限 0600）：
#   root_password, tdyw_app_password, tdyw_migrate_password,
#   tdyw_backup_password, tdyw_monitor_password, tdyw_dba_password
#
# 可通过环境变量覆盖默认路径：
#   SECRETS_DIR=/custom/path bash .../run_init.sh
# ================================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SECRETS_DIR="${SECRETS_DIR:-${PROJECT_ROOT}/docker/secrets}"

# 自动映射 secret 文件 → 环境变量（仅在用户未手动指定时填充）
auto_set() {
    local file_env="$1" file_name="$2"
    if [ -z "${!file_env:-}" ] && [ -f "${SECRETS_DIR}/${file_name}" ]; then
        export "$file_env"="${SECRETS_DIR}/${file_name}"
    fi
}

auto_set MYSQL_ROOT_PASSWORD_FILE    root_password
auto_set TDYW_APP_PASSWORD_FILE      tdyw_app_password
auto_set TDYW_MIGRATE_PASSWORD_FILE  tdyw_migrate_password
auto_set TDYW_BACKUP_PASSWORD_FILE   tdyw_backup_password
auto_set TDYW_MONITOR_PASSWORD_FILE  tdyw_monitor_password
auto_set TDYW_DBA_PASSWORD_FILE      tdyw_dba_password

# 检查必需的 secret 文件是否存在
missing=()
for f in root_password tdyw_app_password tdyw_migrate_password \
         tdyw_backup_password tdyw_monitor_password tdyw_dba_password; do
    if [ ! -f "${SECRETS_DIR}/${f}" ]; then
        missing+=("${f}")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "[ERROR] 以下 secret 文件缺失于 ${SECRETS_DIR}/：" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "" >&2
    echo "请创建（生产 Linux 上）：" >&2
    echo "  mkdir -p ${SECRETS_DIR}" >&2
    echo "  openssl rand -base64 24 > ${SECRETS_DIR}/root_password" >&2
    echo "  openssl rand -base64 24 > ${SECRETS_DIR}/tdyw_app_password" >&2
    echo "  openssl rand -base64 24 > ${SECRETS_DIR}/tdyw_migrate_password" >&2
    echo "  openssl rand -base64 24 > ${SECRETS_DIR}/tdyw_backup_password" >&2
    echo "  openssl rand -base64 24 > ${SECRETS_DIR}/tdyw_monitor_password" >&2
    echo "  openssl rand -base64 24 > ${SECRETS_DIR}/tdyw_dba_password" >&2
    echo "  chmod 600 ${SECRETS_DIR}/*" >&2
    echo "" >&2
    echo "root_password 可从 docker/.env 提取：" >&2
    echo "  grep '^MYSQL_ROOT_PASSWORD=' docker/.env | cut -d= -f2- > ${SECRETS_DIR}/root_password" >&2
    exit 2
fi

echo "[wrapper] SECRETS_DIR=${SECRETS_DIR}"
echo "[wrapper] DB_ACCOUNTS_CONFIRM=${DB_ACCOUNTS_CONFIRM:-NO}"
echo "[wrapper] 即将调用 init_db_accounts.sh"
echo ""

exec bash "${SCRIPT_DIR}/init_db_accounts.sh"
