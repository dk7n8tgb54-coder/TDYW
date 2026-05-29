#!/bin/bash
set -e

echo "=========================================="
echo "Spug 运维平台 - 启动脚本"
echo "=========================================="

# 等待数据库就绪
echo "等待数据库连接..."
while ! nc -z ${MYSQL_HOST:-db} ${MYSQL_PORT:-3306} 2>/dev/null; do
    echo "数据库未就绪，等待 5 秒..."
    sleep 5
done
echo "数据库已连接"

# 执行数据库迁移
echo "执行数据库迁移..."
cd /data/spug/spug_api
python manage.py migrate --noinput || echo "迁移失败或已跳过"

# 收集静态文件
echo "收集静态文件..."
python manage.py collectstatic --noinput || echo "收集静态文件失败或已跳过"

# 初始化管理员账号（如果不存在）
echo "检查管理员账号..."
python manage.py shell -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()
from apps.account.models import User
if not User.objects.filter(username='admin').exists():
    user = User.objects.create(
        username='admin',
        nickname='管理员',
        password_hash=User.make_password('Admin888'),
        is_supper=True,
        is_active=True
    )
    print('管理员账号已创建: admin / Admin888')
else:
    print('管理员账号已存在')
" || echo "初始化管理员失败或已跳过"

echo "=========================================="
echo "Spug 运维平台启动完成"
echo "访问地址: http://localhost"
echo "默认账号: admin / Admin888"
echo "=========================================="

# 执行传入的命令
exec "$@"
