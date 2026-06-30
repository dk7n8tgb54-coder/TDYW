#!/bin/bash
# MySQL 启动脚本
# 功能：复制配置文件并设置正确权限，然后启动 MySQL

set -e

# 从临时位置复制配置文件到目标位置（解决 Windows 权限问题）
if [ -f /tmp/mysql-config/custom.cnf ]; then
    echo "[Entrypoint] 复制 MySQL 配置文件..."
    cp /tmp/mysql-config/custom.cnf /etc/mysql/conf.d/custom.cnf
    chmod 644 /etc/mysql/conf.d/custom.cnf
    echo "[Entrypoint] 配置文件权限已设置为 644"
fi

# 执行原始的 MySQL entrypoint
exec docker-entrypoint.sh "$@"
