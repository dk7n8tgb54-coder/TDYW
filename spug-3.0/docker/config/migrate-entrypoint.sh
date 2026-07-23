#!/bin/bash
# ================================================================================
# 独立 Migration 入口脚本（第二阶段：非 root 化改造）
# --------------------------------------------------------------------------------
# 用途：供 docker-compose.yml 的 tdyw-migrate service 使用。
#       只执行数据库迁移，不启动长期运行的应用进程。
#       使用 tdyw_migrate 账号（有 DDL 权限），不使用 tdyw_app（无 DDL 权限）。
#
# 安全约束：
#   - migration 完成后容器退出，不长期运行
#   - migration 失败时返回非零退出码，阻止应用启动
#   - 不执行 collectstatic / admin init（由应用容器在启动时处理）
# ================================================================================
set -e

echo "=========================================="
echo "Spug 数据库迁移服务（tdyw_migrate）"
echo "=========================================="

# 等待数据库就绪
echo "等待数据库连接..."
while ! nc -z ${MYSQL_HOST:-db} ${MYSQL_PORT:-3306} 2>/dev/null; do
    echo "数据库未就绪，等待 5 秒..."
    sleep 5
done
echo "数据库已连接"

cd /data/spug/spug_api

echo "当前数据库账号: ${MYSQL_USER:-未设置}"
echo "目标数据库: ${MYSQL_DATABASE:-未设置}"

# 执行数据库迁移
# tdyw_migrate 拥有 CREATE, ALTER, DROP, INDEX, REFERENCES + DML 权限
echo "执行数据库迁移..."
python manage.py migrate --noinput
MIGRATE_RC=$?

if [ $MIGRATE_RC -ne 0 ]; then
    echo "[ERROR] 数据库迁移失败（退出码 $MIGRATE_RC）"
    echo "[ERROR] 应用不应使用 tdyw_app 尝试 DDL（tdyw_app 无 DDL 权限会失败）"
    exit $MIGRATE_RC
fi

echo "[OK] 数据库迁移完成"

# 初始化文档系统目录（幂等，只需 DML 权限）
echo "初始化文档系统目录..."
python manage.py init_document_system_folders || echo "[WARN] 文档系统目录初始化失败或已跳过"

echo "=========================================="
echo "Migration service 完成，容器将退出"
echo "=========================================="
