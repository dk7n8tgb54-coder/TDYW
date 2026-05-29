#!/bin/bash
# 回收站功能Docker测试脚本
# 使用方法: ./docker-test-recycle-bin.sh

set -e

echo "=========================================="
echo "    回收站功能Docker测试脚本"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查Docker是否运行
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}[错误] Docker未运行，请先启动Docker${NC}"
    exit 1
fi

echo -e "${GREEN}[✓] Docker运行正常${NC}"
echo ""

# 获取容器名称
API_CONTAINER=$(docker ps --filter "name=api" --format "{{.Names}}" | head -n 1)

if [ -z "$API_CONTAINER" ]; then
    echo -e "${YELLOW}[警告] 未找到api容器，尝试查找其他可能的容器名...${NC}"
    API_CONTAINER=$(docker ps --format "{{.Names}}" | grep -E "(api|backend|spug)" | head -n 1)
fi

if [ -z "$API_CONTAINER" ]; then
    echo -e "${RED}[错误] 未找到API容器，请确保项目已启动${NC}"
    echo "可用的容器列表:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    exit 1
fi

echo -e "${GREEN}[✓] 找到API容器: $API_CONTAINER${NC}"
echo ""

# 检查Python语法
echo "[1/5] 执行Python语法检查..."
docker exec $API_CONTAINER python -m py_compile apps/document/models.py
docker exec $API_CONTAINER python -m py_compile apps/document/views/recycle_bin.py
docker exec $API_CONTAINER python -m py_compile apps/document/urls.py
docker exec $API_CONTAINER python -m py_compile apps/document/tasks/cleanup.py
docker exec $API_CONTAINER python -m py_compile tests/test_recycle_bin.py
echo -e "${GREEN}[✓] 语法检查全部通过${NC}"
echo ""

# 检查数据库迁移
echo "[2/5] 检查数据库迁移状态..."
docker exec $API_CONTAINER python manage.py showmigrations document | grep -E "(X|\[ \])"
echo ""

# 执行单元测试
echo "[3/5] 执行回收站单元测试..."
docker exec $API_CONTAINER python manage.py test tests.test_recycle_bin -v 2
echo ""

# 检查Celery任务注册
echo "[4/5] 检查Celery任务注册..."
docker exec $API_CONTAINER python -c "from celery import current_app; tasks = [t for t in current_app.tasks.keys() if 'recycle' in t or 'cleanup' in t]; print('注册的任务:', tasks)"
echo ""

# 检查定时任务配置
echo "[5/5] 检查定时任务配置..."
docker exec $API_CONTAINER python -c "
from celery.schedules import crontab
from apps.document.celery_beat_schedule import DOCUMENT_BEAT_SCHEDULE
import json
tasks = {k: str(v.get('schedule', 'N/A')) for k, v in DOCUMENT_BEAT_SCHEDULE.items()}
print('定时任务配置:')
for name, schedule in tasks.items():
    print(f'  - {name}: {schedule}')
"
echo ""

echo "=========================================="
echo -e "${GREEN}    测试执行完成！${NC}"
echo "=========================================="
