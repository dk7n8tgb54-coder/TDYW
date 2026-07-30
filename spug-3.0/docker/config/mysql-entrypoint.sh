#!/bin/bash
# MySQL 启动脚本
# 功能：复制配置文件，启动 MySQL，自动确保应用账号存在

set -e

# 从临时位置复制配置文件到目标位置（解决 Windows 权限问题）
if [ -f /tmp/mysql-config/custom.cnf ]; then
    echo "[Entrypoint] 复制 MySQL 配置文件..."
    cp /tmp/mysql-config/custom.cnf /etc/mysql/conf.d/custom.cnf
    chmod 644 /etc/mysql/conf.d/custom.cnf
    echo "[Entrypoint] 配置文件权限已设置为 644"
fi

# 后台启动 MySQL 原始入口
docker-entrypoint.sh "$@" &
MYSQL_PID=$!

# 等待 MySQL 就绪
echo "[Entrypoint] 等待 MySQL 启动..."
until mysqladmin ping -h 127.0.0.1 -u root -p"${MYSQL_ROOT_PASSWORD}" --silent 2>/dev/null; do
    sleep 1
done
echo "[Entrypoint] MySQL 已就绪"

# 自动确保应用账号存在（每次启动都检查，已有则跳过）
if [ -n "${MYSQL_USER}" ] && [ -n "${MYSQL_PASSWORD}" ]; then
    echo "[Entrypoint] 检查应用账号 ${MYSQL_USER}..."
    mysql -u root -p"${MYSQL_ROOT_PASSWORD}" -e "
        CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
        GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
        ON ${MYSQL_DATABASE:-tdyw}.* TO '${MYSQL_USER}'@'%';
        FLUSH PRIVILEGES;
    " 2>/dev/null && echo "[Entrypoint] 应用账号 ${MYSQL_USER} 已就绪" \
      || echo "[Entrypoint] 警告: 应用账号检查失败，请手动检查"
fi

# 等待 MySQL 主进程退出
wait $MYSQL_PID
