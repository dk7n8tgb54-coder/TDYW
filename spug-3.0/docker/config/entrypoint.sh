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

# 初始化文档系统目录（党建文档等，幂等，每次启动自动确保绑定存在）
echo "初始化文档系统目录..."
python manage.py init_document_system_folders || echo "文档系统目录初始化失败或已跳过"

# 收集静态文件
echo "收集静态文件..."
python manage.py collectstatic --noinput || echo "收集静态文件失败或已跳过"

# 初始化管理员账号（如果不存在）
echo "检查管理员账号..."
admin_init_output=$(python manage.py shell -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()
from apps.account.models import User
if not User.objects.filter(username='admin').exists():
    user = User.objects.create(
        username='admin',
        nickname='管理员',
        password_hash=User.make_password('Admin888..'),
        is_supper=True,
        is_active=True
    )
    print('管理员账号已创建: admin / Admin888..')
else:
    print('管理员账号已存在')
" 2>&1) || admin_init_output="${admin_init_output}
初始化管理员失败或已跳过"
echo "${admin_init_output}"

echo "=========================================="
echo "Spug 运维平台启动完成"
echo "访问地址: http://localhost"
# 仅首次创建账号时提示默认凭据，避免每次启动都把默认口令打进容器日志
case "${admin_init_output}" in
    *管理员账号已创建*) echo "默认账号: admin / Admin888.." ;;
esac
echo "=========================================="

# 执行传入的命令
exec "$@"
