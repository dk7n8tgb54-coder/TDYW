# 回收站P0问题修复 - Docker环境部署指南

## 一、数据库迁移（Docker环境）

### 1.1 进入API容器执行迁移

```bash
# 进入spug-api容器
docker exec -it spug-api /bin/sh

# 在容器内执行迁移
cd /data/spug/spug_api
python manage.py makemigrations document --name add_pending_clean_fields
python manage.py migrate

# 退出容器
exit
```

### 1.2 验证迁移结果

```bash
# 进入MySQL容器验证字段
docker exec -it spug-mysql mysql -uroot -p<密码> -e "
USE spug;
SELECT COLUMN_NAME, DATA_TYPE 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_SCHEMA = 'spug' 
AND TABLE_NAME = 'spug_document_file_private'
AND COLUMN_NAME IN ('is_pending_clean', 'clean_retry_count', 'last_clean_attempt');
"
```

预期输出：
```
+------------------+------------------+
| COLUMN_NAME      | DATA_TYPE        |
+------------------+------------------+
| is_pending_clean | tinyint          |
| clean_retry_count| int              |
| last_clean_attempt| datetime        |
+------------------+------------------+
```

---

## 二、Celery定时任务配置（Docker环境）

### 2.1 代码变更已自动生效

由于代码已通过volume挂载到容器中，之前的配置修改已自动生效：
- `apps/document/tasks/__init__.py` - 导出 `retry_clean_pending_files`
- `spug/celery.py` - 导入新任务
- `spug/settings.py` - 配置队列路由和定时任务

### 2.2 重启Celery服务

```bash
# 方式1：使用docker-compose重启
cd /path/to/your/docker-compose
docker-compose restart spug-beat spug-worker

# 方式2：进入容器重启supervisor
docker exec -it spug-api supervisorctl restart spug-beat spug-worker

# 方式3：完全重启API容器
docker-compose restart spug-api
```

### 2.3 验证任务注册

```bash
# 进入API容器
docker exec -it spug-api /bin/sh

# 检查已注册的任务
cd /data/spug/spug_api
python -c "
from spug.celery import app
tasks = [t for t in app.tasks.keys() if 'cleanup' in t]
print('已注册的清理任务:')
for t in tasks:
    print(f'  - {t}')
"

# 退出
exit
```

预期输出包含：
```
已注册的清理任务:
  - apps.document.tasks.cleanup.retry_clean_pending_files
  - apps.document.tasks.cleanup.cleanup_soft_deleted_files
  - apps.document.tasks.cleanup.async_batch_permanent_delete
```

### 2.4 验证Beat调度器

```bash
# 查看Beat日志
docker logs spug-api -f | grep -i beat

# 或查看supervisor状态
docker exec spug-api supervisorctl status spug-beat
```

预期状态：`spug-beat RUNNING`

---

## 三、回归验证（Docker环境）

### 3.1 快速验证脚本

创建验证脚本并执行：

```bash
# 将验证脚本复制到容器
docker cp verify_p0_fixes.py spug-api:/tmp/

# 进入容器执行
docker exec -it spug-api /bin/sh
cd /data/spug/spug_api
python /tmp/verify_p0_fixes.py
```

### 3.2 手动验证清单

#### P0-1: 硬删除权限检查
```bash
# 使用普通用户token测试（应返回403）
curl -X POST http://localhost/api/document/recycle-bin/permanent-delete/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token <普通用户token>" \
  -d '{"ids": [1], "space_type": "private"}'

# 预期响应
{"error": "只有管理员可以硬删除文件", "code": 403}
```

#### P0-2: 分页ID冲突
```bash
# 调用回收站列表，检查space_type字段
curl "http://localhost/api/document/recycle-bin/?page=1&size=10" \
  -H "Authorization: Token <token>" | jq '.data[].space_type'

# 预期：每个文件都有正确的space_type（private/public）
```

#### P0-3: 90天截断移除
```bash
# 检查代码中是否还有90天截断逻辑
docker exec spug-api grep -n "90" /data/spug/spug_api/apps/document/views/recycle_bin.py

# 预期：无相关代码（已删除）
```

#### P0-4: 并发恢复竞态条件
```bash
# 检查代码中是否有select_for_update
docker exec spug-api grep -n "select_for_update" /data/spug/spug_api/apps/document/views/recycle_bin.py

# 预期：有行锁代码
```

#### P0-5: 异步任务用户状态校验
```bash
# 检查cleanup.py中的用户状态校验
docker exec spug-api grep -n "is_active" /data/spug/spug_api/apps/document/tasks/cleanup.py

# 预期：有用户状态检查代码
```

#### P0-6: 物理删除兜底
```bash
# 检查模型中的is_pending_clean字段处理
docker exec spug-api grep -n "is_pending_clean" /data/spug/spug_api/apps/document/models.py

# 预期：有字段定义和delete方法处理
```

#### P0-7: 清理任务重试
```bash
# 手动触发清理任务
docker exec -it spug-api /bin/sh
cd /data/spug/spug_api
python -c "
from apps.document.tasks.cleanup import retry_clean_pending_files
result = retry_clean_pending_files.delay()
print(f'Task ID: {result.id}')
"

# 查看任务结果（等待几秒后）
python -c "
from celery.result import AsyncResult
from spug.celery import app
result = AsyncResult('上面输出的task_id', app=app)
print(result.get(timeout=10))
"
```

---

## 四、Docker Compose配置检查

### 4.1 确认服务配置

检查 `docker-compose.yml` 中的Celery服务配置：

```yaml
# 应该包含以下服务
services:
  spug-api:
    # ... 其他配置
    volumes:
      - ./spug_api:/data/spug/spug_api  # 代码挂载
      
  spug-worker:
    command: celery -A spug worker -l info -Q document.merge,document.batch,document.cleanup
    volumes:
      - ./spug_api:/data/spug/spug_api
      
  spug-beat:
    command: celery -A spug beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    volumes:
      - ./spug_api:/data/spug/spug_api
```

### 4.2 队列检查

```bash
# 查看Celery队列状态
docker exec spug-api celery -A spug inspect active_queues

# 预期输出包含 document.cleanup 队列
```

---

## 五、监控与日志

### 5.1 查看清理任务日志

```bash
# 实时查看API日志
docker logs spug-api -f | grep -i "cleanup\|pending\|recycle"

# 查看Worker日志
docker logs spug-worker -f | grep -i "cleanup"

# 查看Beat日志
docker logs spug-beat -f
```

### 5.2 告警检查

超过3次重试失败的文件会产生CRITICAL日志：

```bash
# 搜索关键日志
docker logs spug-api | grep "CRITICAL\|需人工介入"
```

---

## 六、一键验证脚本

创建 `docker_verify.sh`：

```bash
#!/bin/bash
# 回收站P0修复Docker环境验证脚本

echo "======================================"
echo "回收站P0修复验证 - Docker环境"
echo "======================================"

# 检查容器运行状态
echo -e "\n[1/5] 检查容器状态..."
docker-compose ps | grep -E "spug-api|spug-worker|spug-beat"

# 执行数据库迁移
echo -e "\n[2/5] 执行数据库迁移..."
docker exec spug-api python /data/spug/spug_api/manage.py migrate

# 检查Celery任务注册
echo -e "\n[3/5] 检查Celery任务..."
docker exec spug-api python -c "
from spug.celery import app
tasks = [t for t in app.tasks.keys() if 'cleanup' in t]
print('已注册清理任务:', len(tasks))
for t in tasks:
    print(f'  ✓ {t}')
"

# 检查模型字段
echo -e "\n[4/5] 检查模型字段..."
docker exec spug-api python -c "
from apps.document.models import DocumentFilePrivate, DocumentFilePublic
required = ['is_pending_clean', 'clean_retry_count', 'last_clean_attempt']
private_fields = [f.name for f in DocumentFilePrivate._meta.get_fields()]
public_fields = [f.name for f in DocumentFilePublic._meta.get_fields()]

for f in required:
    status = '✓' if f in private_fields else '✗'
    print(f'  {status} DocumentFilePrivate.{f}')
    status = '✓' if f in public_fields else '✗'
    print(f'  {status} DocumentFilePublic.{f}')
"

# 检查定时任务配置
echo -e "\n[5/5] 检查定时任务..."
docker exec spug-api python -c "
from django.conf import settings
schedule = settings.CELERY_BEAT_SCHEDULE
if 'retry-clean-pending-files' in schedule:
    print('  ✓ 定时任务已配置')
    print(f"    任务: {schedule[\"retry-clean-pending-files\"][\"task\"]}")
    print(f"    间隔: {schedule[\"retry-clean-pending-files\"][\"schedule\"]}秒")
else:
    print('  ✗ 定时任务未配置')
"

echo -e "\n======================================"
echo "验证完成"
echo "======================================"
```

执行：
```bash
chmod +x docker_verify.sh
./docker_verify.sh
```

---

## 七、部署检查清单

| 检查项 | 状态 | 备注 |
|--------|------|------|
| 数据库迁移完成 | ⬜ | `is_pending_clean`等字段已添加 |
| Celery Worker运行 | ⬜ | `docker-compose ps`显示running |
| Celery Beat运行 | ⬜ | 定时调度器正常 |
| 任务已注册 | ⬜ | `retry_clean_pending_files`在任务列表中 |
| 定时任务配置 | ⬜ | 每小时执行一次 |
| 权限检查生效 | ⬜ | 普通用户硬删除返回403 |
| 分页ID冲突修复 | ⬜ | `_space_type`字段正确标记 |
| 90天截断移除 | ⬜ | 大偏移量查询正常 |
| 并发恢复锁 | ⬜ | `select_for_update`生效 |
| 用户状态校验 | ⬜ | 禁用用户无法执行异步删除 |
| 物理删除兜底 | ⬜ | 失败时标记pending状态 |
| 清理重试任务 | ⬜ | 定时重试pending文件 |

---

## 八、常见问题

### Q1: 迁移后字段不存在？
```bash
# 检查迁移文件是否生成
docker exec spug-api ls -la /data/spug/spug_api/apps/document/migrations/

# 手动执行迁移
docker exec spug-api python /data/spug/spug_api/manage.py migrate document
```

### Q2: Celery任务未注册？
```bash
# 重启服务
docker-compose restart spug-api spug-worker spug-beat

# 检查导入
docker exec spug-api python -c "from apps.document.tasks.cleanup import retry_clean_pending_files; print('导入成功')"
```

### Q3: Beat定时任务不执行？
```bash
# 检查Beat日志
docker logs spug-beat -f

# 确认配置已加载
docker exec spug-api python -c "from django.conf import settings; print(settings.CELERY_BEAT_SCHEDULE)"
```

---

**部署完成后，请在测试环境验证所有P0修复点后再上线生产环境。**
