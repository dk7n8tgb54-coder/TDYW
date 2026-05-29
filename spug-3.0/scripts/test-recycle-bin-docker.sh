#!/bin/bash
# 回收站功能Docker测试脚本
# 适用于容器名: tdyw

set -e

echo "=========================================="
echo "    回收站功能Docker测试脚本"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CONTAINER_NAME="tdyw"

# 检查容器是否运行
if ! docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}[错误] 容器 ${CONTAINER_NAME} 未运行${NC}"
    echo "可用的容器:"
    docker ps --format "table {{.Names}}\t{{.Status}}"
    exit 1
fi

echo -e "${GREEN}[✓] 容器 ${CONTAINER_NAME} 运行正常${NC}"
echo ""

# 进入容器执行测试
docker_exec() {
    docker exec ${CONTAINER_NAME} "$@"
}

# 检查Python语法
echo -e "${BLUE}[1/4] 执行Python语法检查...${NC}"
docker_exec python -m py_compile /data/spug/spug_api/apps/document/models.py
docker_exec python -m py_compile /data/spug/spug_api/apps/document/views/recycle_bin.py
docker_exec python -m py_compile /data/spug/spug_api/apps/document/urls.py
docker_exec python -m py_compile /data/spug/spug_api/apps/document/tasks/cleanup.py
if [ -f "tests/test_recycle_bin.py" ]; then
    docker cp tests/test_recycle_bin.py ${CONTAINER_NAME}:/data/spug/tests/
    docker_exec python -m py_compile /data/spug/tests/test_recycle_bin.py
fi
echo -e "${GREEN}[✓] 语法检查全部通过${NC}"
echo ""

# 检查数据库表结构
echo -e "${BLUE}[2/4] 检查数据库表结构...${NC}"
docker_exec python /data/spug/spug_api/manage.py showmigrations document 2>/dev/null | tail -20 || echo "迁移检查完成"
echo ""

# 检查回收站相关配置
echo -e "${BLUE}[3/4] 检查回收站配置...${NC}"
docker_exec python -c "
import sys
sys.path.insert(0, '/data/spug/spug_api')
import os
os.chdir('/data/spug/spug_api')

import django
django.setup()

from django.conf import settings

print('回收站配置:')
print(f'  RECYCLE_BIN_RETENTION_DAYS: {getattr(settings, \"RECYCLE_BIN_RETENTION_DAYS\", \"未设置\")}')
print(f'  RECYCLE_BIN_BATCH_LIMIT: {getattr(settings, \"RECYCLE_BIN_BATCH_LIMIT\", \"未设置\")}')
print(f'  RECYCLE_BIN_CACHE_TTL: {getattr(settings, \"RECYCLE_BIN_CACHE_TTL\", \"未设置\")}')

# 检查模型方法
from apps.document.models import DocumentFilePrivate
print('')
print('模型方法检查:')
print(f'  delete方法: {\"✓\" if hasattr(DocumentFilePrivate, \"delete\") else \"✗\"}')
print(f'  restore方法: {\"✓\" if hasattr(DocumentFilePrivate, \"restore\") else \"✗\"}')
"
echo ""

# 检查Celery任务
echo -e "${BLUE}[4/4] 检查Celery任务...${NC}"
docker_exec python -c "
import sys
sys.path.insert(0, '/data/spug/spug_api')
import os
os.chdir('/data/spug/spug_api')

from apps.document.celery_beat_schedule import DOCUMENT_BEAT_SCHEDULE

print('定时任务配置:')
for name, config in DOCUMENT_BEAT_SCHEDULE.items():
    if 'cleanup' in name or 'recycle' in name:
        schedule = config.get('schedule', 'N/A')
        print(f'  - {name}: {schedule}')
"
echo ""

echo "=========================================="
echo -e "${GREEN}    环境检查完成！${NC}"
echo "=========================================="
echo ""

# 提示执行测试命令
echo -e "${YELLOW}手动执行单元测试命令:${NC}"
echo "  docker exec ${CONTAINER_NAME} python /data/spug/spug_api/manage.py test tests.test_recycle_bin -v 2"
echo ""
echo -e "${YELLOW}API手动测试:${NC}"
echo "  1. 先获取Token:"
echo "     curl -X POST http://localhost/api/account/login/ \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"username\":\"admin\",\"password\":\"your_password\"}'"
echo ""
echo "  2. 测试回收站列表:"
echo "     curl http://localhost/api/document/recycle-bin/ \\"
echo "       -H 'Authorization: Bearer YOUR_TOKEN'"
