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

# docker stop/compose down 只向 PID 1（本脚本）发 SIGTERM，bash 不会自动转发给
# 后台子进程；必须显式转发给 mysqld，否则它收不到信号，等待期结束后被 SIGKILL
# 强杀，InnoDB 无法优雅关库（表现为等满 stop_grace_period 且无任何关闭日志）
trap 'kill -TERM $MYSQL_PID 2>/dev/null' TERM INT

# 等待 MySQL 就绪
echo "[Entrypoint] 等待 MySQL 启动..."
until mysqladmin ping -h 127.0.0.1 -u root -p"${MYSQL_ROOT_PASSWORD}" --silent 2>/dev/null; do
    sleep 1
done
echo "[Entrypoint] MySQL 已就绪"

# 自动确保应用账号存在
# 必须先只读查询账号是否存在、不存在才执行 CREATE USER：
# CREATE USER ... IDENTIFIED BY '<明文>' 会被 MariaDB 原样写入 binlog，
# 每次启动都执行（含 IF NOT EXISTS）会导致明文密码反复留痕；SELECT 不会写 binlog
if [ -n "${MYSQL_USER}" ] && [ -n "${MYSQL_PASSWORD}" ]; then
    echo "[Entrypoint] 检查应用账号 ${MYSQL_USER}..."
    USER_EXISTS=$(mysql -u root -p"${MYSQL_ROOT_PASSWORD}" -N -e "
        SELECT COUNT(*) FROM mysql.user WHERE user='${MYSQL_USER}' AND host='%';
    " 2>/dev/null)
    if [ "${USER_EXISTS}" = "0" ]; then
        echo "[Entrypoint] 应用账号不存在，开始创建 ${MYSQL_USER}..."
        mysql -u root -p"${MYSQL_ROOT_PASSWORD}" -e "
            CREATE USER '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
        " 2>/dev/null && echo "[Entrypoint] 应用账号 ${MYSQL_USER} 已创建" \
          || echo "[Entrypoint] 警告: 应用账号创建失败，请手动检查"
    else
        echo "[Entrypoint] 应用账号 ${MYSQL_USER} 已存在，跳过创建"
    fi
    # 权限补授语句不含密码，每次启动幂等执行（账号权限缺失时自动修复）
    mysql -u root -p"${MYSQL_ROOT_PASSWORD}" -e "
        GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
        ON ${MYSQL_DATABASE:-tdyw}.* TO '${MYSQL_USER}'@'%';
        FLUSH PRIVILEGES;
    " 2>/dev/null && echo "[Entrypoint] 应用账号 ${MYSQL_USER} 权限已确认" \
      || echo "[Entrypoint] 警告: 应用账号权限确认失败，请手动检查"
fi

# 等待 MySQL 主进程退出
# 第一次 wait 被停止信号打断时（退出码>128，此时 trap 已转发信号），必须再等
# 一次让 mysqld 真正完成优雅关闭；其余情况透传 mysqld 自身的退出码
status=0
wait $MYSQL_PID || status=$?
if [ "$status" -gt 128 ]; then
    wait $MYSQL_PID
    status=$?
fi
exit "$status"
