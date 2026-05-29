# Celery 死信队列（DLQ）配置方案

## 方案概述

**方案名称**：Celery 死信队列配置  
**目标**：防止批量操作和文件处理任务失败后数据丢失  
**核心思想**：任务失败达到最大重试次数后，自动转入死信队列，便于人工处理和恢复  
**适用范围**：资料库模块的所有 Celery 异步任务

---

## 背景与问题

### 当前问题

```
任务提交 → Celery Worker 执行
              ↓
         执行失败（网络/磁盘/数据库问题）
              ↓
         自动重试3次（max_retries=3）
              ↓
         仍失败
              ↓
    ❌ 任务被直接丢弃！数据丢失！
              ↓
    用户：我的批量删除操作失败了吗？
    系统：不知道，任务已经没了...
```

### 具体场景

| 任务类型 | 失败场景 | 后果 |
|---------|---------|------|
| 批量删除传输记录 | 数据库连接中断 | 部分记录未删除，数据不一致 |
| 批量永久删除文件 | 磁盘IO错误 | 数据库记录已删，文件还在 |
| 文件合并 | 磁盘空间不足 | 分片残留，用户需重新上传 |
| 文件夹复制 | 权限问题 | 复制中断，部分文件缺失 |

### 痛点总结

1. **数据丢失**：失败任务直接丢弃，无法恢复
2. **无法排查**：不知道哪些任务失败了，失败原因是什么
3. **用户体验差**：操作失败无感知，数据不一致
4. **难以修复**：无法手动重试，只能重新操作

---

## 死信队列原理

### 什么是死信队列

**死信队列（Dead Letter Queue, DLQ）** = 任务的"墓地"，存储**执行失败且无法重试**的任务。

```
正常队列                    死信交换机              死信队列
┌─────────────┐            ┌─────────────┐        ┌─────────────┐
│ document.   │    失败    │     dlx     │        │ dlq.        │
│ batch       │   3次后   │  (中转站)   │   →    │ document.   │
│ (执行任务)  │ ─────────→ │             │        │ batch       │
└─────────────┘            └─────────────┘        │ (存储失败   │
     │                                            │  任务)      │
     │ 成功执行                                   └─────────────┘
     ↓                                                   ↓
  任务完成                                          人工处理/
                                                    手动重试
```

### 工作流程

```
1. 任务提交到正常队列
        ↓
2. Worker 取出执行
        ↓
3. 执行失败
        ↓
4. 自动重试（最多3次）
        ↓
5. 仍失败 → 发送到死信交换机（DLX）
        ↓
6. 交换机路由到死信队列（DLQ）
        ↓
7. 任务在 DLQ 中存储
        ↓
8. 人工查看/处理/重试
```

---

## 配置方案

### 1. RabbitMQ 配置（推荐用于生产环境）

**文件**: `spug_api/spug/celery.py` 或 `settings.py`

```python
from kombu import Queue, Exchange

# ========== 死信队列配置 ==========

# 死信交换机（所有死信任务的中转站）- 开启持久化
DLX_EXCHANGE = Exchange('dlx', type='direct', durable=True)

# 定义队列（带死信参数）
CELERY_TASK_QUEUES = [
    # ========== 批量操作队列 ==========
    Queue(
        'document.batch',
        exchange=DLX_EXCHANGE,
        routing_key='document.batch',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-dead-letter-exchange': 'dlx',              # ← 死信交换机
            'x-dead-letter-routing-key': 'dlq.document.batch'  # ← 死信路由键
        }
    ),
    # 对应的死信队列（带TTL，7天后自动清理）
    Queue(
        'dlq.document.batch',
        exchange=DLX_EXCHANGE,
        routing_key='dlq.document.batch',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-message-ttl': 7 * 24 * 60 * 60 * 1000,  # 7天（毫秒）
        }
    ),

    # ========== 文件合并队列 ==========
    Queue(
        'document.merge',
        exchange=DLX_EXCHANGE,
        routing_key='document.merge',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-dead-letter-exchange': 'dlx',
            'x-dead-letter-routing-key': 'dlq.document.merge'
        }
    ),
    Queue(
        'dlq.document.merge',
        exchange=DLX_EXCHANGE,
        routing_key='dlq.document.merge',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-message-ttl': 7 * 24 * 60 * 60 * 1000,
        }
    ),

    # ========== 文件清理队列 ==========
    Queue(
        'document.cleanup',
        exchange=DLX_EXCHANGE,
        routing_key='document.cleanup',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-dead-letter-exchange': 'dlx',
            'x-dead-letter-routing-key': 'dlq.document.cleanup'
        }
    ),
    Queue(
        'dlq.document.cleanup',
        exchange=DLX_EXCHANGE,
        routing_key='dlq.document.cleanup',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-message-ttl': 7 * 24 * 60 * 60 * 1000,
        }
    ),
    
    # ========== 文件夹复制队列 ==========
    Queue(
        'document.folder.copy',
        exchange=DLX_EXCHANGE,
        routing_key='document.folder.copy',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-dead-letter-exchange': 'dlx',
            'x-dead-letter-routing-key': 'dlq.document.folder.copy'
        }
    ),
    # 死信队列（带TTL自动清理，避免无限积压）
    Queue(
        'dlq.document.folder.copy',
        exchange=DLX_EXCHANGE,
        routing_key='dlq.document.folder.copy',
        durable=True,  # 显式声明队列持久化
        queue_arguments={
            'x-message-ttl': 7 * 24 * 60 * 60 * 1000,  # 7天（毫秒）
        }
    ),
]

# ========== 死信队列必须的核心Celery配置 ==========
# 1. 任务执行成功后才ACK，失败的任务不会被ACK，才能触发死信
CELERY_TASK_ACKS_LATE = True
# 2. Worker意外崩溃/被杀时，消息重新入队，避免任务丢失
CELERY_TASK_REJECT_ON_WORKER_LOST = True
# 3. 队列镜像策略（RabbitMQ集群场景），保证队列高可用
CELERY_TASK_QUEUE_HA_POLICY = 'all'
# 4. 长耗时任务预取数设为1，避免任务被单个Worker锁住，负载不均
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# 默认队列路由
CELERY_TASK_DEFAULT_QUEUE = 'document.batch'
CELERY_TASK_DEFAULT_EXCHANGE = 'document'
CELERY_TASK_DEFAULT_ROUTING_KEY = 'document.batch'

# 任务路由配置
CELERY_TASK_ROUTES = {
    # 批量操作
    'apps.document.tasks.batch_delete_transfers': {'queue': 'document.batch'},
    'apps.document.tasks.batch_cancel_transfers': {'queue': 'document.batch'},
    
    # 文件合并
    'apps.document.tasks.merge_file_chunks': {'queue': 'document.merge'},
    
    # 文件清理
    'apps.document.tasks.async_batch_permanent_delete': {'queue': 'document.cleanup'},
    'apps.document.tasks.async_batch_folder_permanent_delete': {'queue': 'document.cleanup'},
    
    # 文件夹复制
    'apps.document.tasks.async_copy_folder': {'queue': 'document.folder.copy'},
}
```

### 配置统一管理（推荐）

为避免硬编码，建议将所有DLQ相关配置集中到settings.py：

```python
# settings.py - DLQ配置统一管理

# ========== 死信队列通用配置 ==========
CELERY_DLQ_CONFIG = {
    # DLQ前缀
    'prefix': 'dlq',
    # 死信交换机名称
    'dlx_exchange': 'dlx',
    # 消息TTL（毫秒）：7天
    'message_ttl': 7 * 24 * 60 * 60 * 1000,
    # 告警阈值：超过1个任务即告警
    'alert_threshold': 1,
    # 保留天数
    'retention_days': 7,
}

# 任务超时配置（秒）
CELERY_TASK_TIMEOUTS = {
    # 批量操作：5分钟软超时，10分钟硬超时
    'document.batch': {'soft': 300, 'hard': 600},
    # 文件合并：10分钟软超时，20分钟硬超时
    'document.merge': {'soft': 600, 'hard': 1200},
    # 文件清理：5分钟软超时，10分钟硬超时
    'document.cleanup': {'soft': 300, 'hard': 600},
    # 文件夹复制：10分钟软超时，20分钟硬超时
    'document.folder.copy': {'soft': 600, 'hard': 1200},
}

# 重试配置
CELERY_RETRY_CONFIG = {
    'max_retries': 3,
    'default_retry_delay': 30,
    'retry_backoff': True,
    'retry_backoff_max': 600,
}

# 异常分类：可重试 vs 不可重试
CELERY_RETRYABLE_EXCEPTIONS = (
    'ConnectionError',
    'TimeoutError',
    'OperationalError',  # 数据库连接问题
    'IOError',
)

CELERY_NON_RETRYABLE_EXCEPTIONS = (
    'ValueError',
    'TypeError',
    'KeyError',
    'PermissionError',  # 权限问题
    'FileNotFoundError',
)
```

### 2. Redis 配置（开发/测试环境）

如果使用 Redis 作为 Broker，配置方式略有不同：

```python
# settings.py

CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# Redis 死信队列实现（使用单独的队列模拟）
CELERY_TASK_QUEUES = [
    Queue('document.batch'),
    Queue('document.merge'),
    Queue('document.cleanup'),
    Queue('document.folder.copy'),
    # 死信队列（后缀 dlq）
    Queue('dlq.document.batch'),
    Queue('dlq.document.merge'),
    Queue('dlq.document.cleanup'),
    Queue('dlq.document.folder.copy'),
]

# 任务失败后手动路由到死信队列
CELERY_TASK_ANNOTATIONS = {
    '*': {
        'on_failure': 'apps.document.tasks.utils.move_to_dlq',
    }
}
```

**辅助函数**:

```python
# apps/document/tasks/utils.py

import logging
from celery import current_app

logger = logging.getLogger(__name__)

def move_to_dlq(task, exc, task_id, args, kwargs, einfo):
    """
    任务最终失败（达到最大重试次数）时移动到死信队列
    """
    try:
        # 核心判断：仅达到最大重试次数，才进入DLQ
        max_retries = task.max_retries if hasattr(task, 'max_retries') else 3
        current_retries = task.request.retries
        if current_retries < max_retries:
            logger.info(f'[DLQ] 任务重试中，暂不进入DLQ: task={task.name}, retries={current_retries}/{max_retries}')
            return

        # 获取原始队列
        original_queue = task.request.delivery_info.get('routing_key', 'document.batch')
        dlq_name = f"dlq.{original_queue}"
        
        # 发送到死信队列
        current_app.send_task(
            task.name,
            args=args,
            kwargs=kwargs,
            queue=dlq_name,
            task_id=f"{task_id}_dlq",
            headers={
                'x-original-queue': original_queue,
                'x-failure-time': timezone.now().isoformat(),
                'x-failure-reason': str(exc),
                'x-traceback': einfo.traceback if einfo else None,
            }
        )
        
        logger.warning(
            f'[DLQ] 任务已移动到死信队列: task={task.name}, '
            f'original_queue={original_queue}, dlq={dlq_name}'
        )
        
    except Exception as e:
        logger.error(f'[DLQ] 移动到死信队列失败: {e}')
```

---

## 任务配置

### 任务幂等性设计（关键！）

**为什么需要幂等性**：由于任务会被自动重试（3次）或手动重试，若任务不幂等，可能导致重复删除数据、文件重复合并等问题。

**幂等性保证原则**：
1. **状态检查**：执行前先检查记录是否已处理
2. **数据库事务**：使用原子操作保证一致性
3. **操作日志**：记录处理结果便于追溯

**示例**：

```python
# apps/document/tasks/batch.py

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    retry_backoff=True,
    retry_backoff_max=600,
    queue='document.batch',
)
def batch_delete_transfers(self, transfer_ids, request_user_id, request_tenant_id):
    """
    批量删除传输记录（幂等性设计）
    """
    success_count = 0
    failed_count = 0
    
    for transfer_id in transfer_ids:
        try:
            # 【幂等性】1. 先检查记录是否存在且未删除
            transfer = DocumentTransfer.objects.filter(
                id=transfer_id,
                status__in=['completed', 'failed']  # 只删除已完成或失败的任务
            ).first()
            
            if not transfer:
                logger.info(f'[BatchDelete] 传输记录不存在或已删除: id={transfer_id}')
                continue
            
            # 【幂等性】2. 使用数据库事务保证原子性
            with transaction.atomic():
                # 删除数据库记录
                transfer.delete()
                
                # 记录操作日志
                OperationLog.objects.create(
                    module='document',
                    action='batch_delete_transfer',
                    target_id=transfer_id,
                    operator_id=request_user_id,
                    detail=f'批量删除传输记录: {transfer_id}'
                )
                
                success_count += 1
                logger.info(f'[BatchDelete] 删除成功: id={transfer_id}')
                
        except Exception as e:
            failed_count += 1
            logger.error(f'[BatchDelete] 删除失败: id={transfer_id}, error={e}')
            # 单条失败不影响其他记录
            continue
    
    # 记录批量操作结果
    logger.info(
        f'[BatchDelete] 批量删除完成: '
        f'success={success_count}, failed={failed_count}, '
        f'total={len(transfer_ids)}'
    )
    
    # 如果有失败，触发重试
    if failed_count > 0:
        try:
            self.retry(exc=Exception(f'{failed_count} 个记录删除失败'))
        except MaxRetriesExceededError:
            # 达到最大重试次数，记录日志，必须抛出异常触发死信
            logger.critical(
                f'[BatchDelete] 任务最终失败，已进入死信队列: '
                f'transfer_ids={transfer_ids}, user={request_user_id}, failed_count={failed_count}'
            )
            # 核心：必须抛出异常，否则Celery会ACK消息，不会进入DLQ
            raise
```

**其他任务的幂等性策略**：

| 任务类型 | 幂等性策略 |
|---------|-----------|
| 批量删除 | 检查记录是否存在，使用事务 |
| 文件合并 | 检查目标文件是否已存在，避免重复合并 |
| 文件删除 | 检查文件状态，已删除则跳过 |
| 文件夹复制 | 使用唯一约束或临时标记防止重复 |

---

### 异常分类处理

区分**可重试异常**和**不可重试异常**，避免无效重试：

```python
# apps/document/tasks/utils.py

import logging
from celery.exceptions import Ignore

logger = logging.getLogger(__name__)

# 可重试异常类型
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,  # IO错误
)

# 不可重试异常类型（直接进入DLQ）
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,
    TypeError,
    KeyError,
    PermissionError,
)


def classify_exception(exc):
    """
    分类异常，决定是否可以重试
    
    Returns:
        tuple: (should_retry, reason)
    """
    if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
        return False, f'不可重试异常: {type(exc).__name__}'
    
    if isinstance(exc, RETRYABLE_EXCEPTIONS):
        return True, f'可重试异常: {type(exc).__name__}'
    
    # 默认可重试
    return True, f'未知异常，尝试重试: {type(exc).__name__}'


# 使用示例
def batch_delete_with_exception_handling(self, transfer_ids, request_user_id, request_tenant_id):
    """
    带异常分类的批量删除
    """
    try:
        # ... 业务逻辑 ...
        pass
    except Exception as exc:
        should_retry, reason = classify_exception(exc)
        
        if not should_retry:
            # 不可重试异常，直接记录并进入DLQ（不重试）
            logger.critical(
                f'[BatchDelete] 不可重试异常，直接进入DLQ: '
                f'reason={reason}, exc={exc}'
            )
            # 抛出异常，Celery会直接进入DLQ（因为不重试）
            raise
        
        # 可重试异常，正常重试
        logger.warning(f'[BatchDelete] 可重试异常: {reason}, 准备重试')
        self.retry(exc=exc)
```

---

### 现有任务修改

所有异步任务需要添加 `max_retries` 和 `retry_backoff`：

```python
# apps/document/tasks/batch.py

@shared_task(
    bind=True,
    max_retries=3,                    # ← 最多重试3次
    default_retry_delay=30,           # ← 首次重试延迟30秒
    retry_backoff=True,               # ← 指数退避
    retry_backoff_max=600,            # ← 最大退避10分钟
    queue='document.batch',
    soft_time_limit=300,              # ← 软超时5分钟，触发异常可捕获
    time_limit=600,                   # ← 硬超时10分钟，直接杀死进程释放资源
)
def batch_delete_transfers(self, transfer_ids, request_user_id, request_tenant_id):
    """
    批量删除传输记录
    失败后自动重试3次，仍失败则进入死信队列
    """
    try:
        # ... 业务逻辑 ...
        pass
    except Exception as exc:
        # 记录失败信息
        logger.error(f'[BatchDelete] 删除失败: {exc}')
        
        # 重试 - 不需要手动捕获MaxRetriesExceededError
        # Celery会在达到最大重试次数后自动抛出异常，触发死信
        self.retry(exc=exc)


### 任务列表

| 任务函数 | 队列 | max_retries | soft_time_limit | time_limit | 说明 |
|---------|------|-------------|-----------------|------------|------|
| `batch_delete_transfers` | document.batch | 3 | 300s | 600s | 批量删除传输记录 |
| `batch_cancel_transfers` | document.batch | 3 | 300s | 600s | 批量取消传输 |
| `merge_file_chunks` | document.merge | 3 | 600s | 1200s | 合并文件分片 |
| `async_batch_permanent_delete` | document.cleanup | 3 | 300s | 600s | 批量永久删除文件 |
| `async_batch_folder_permanent_delete` | document.cleanup | 3 | 300s | 600s | 批量永久删除文件夹 |
| `async_copy_folder` | document.folder.copy | 3 | 600s | 1200s | 异步复制文件夹 |

---

## 监控与管理

### 1. 命令行工具

```bash
# 查看队列状态
celery -A spug inspect active_queues

# 查看死信队列中的任务数（RabbitMQ）
rabbitmqctl list_queues name messages | grep dlq

# 查看 Worker 状态
celery -A spug inspect stats

# ⚠️ 注意：不要直接清理死信队列，应先检查失败原因
# 如需清理，使用 RabbitMQ 管理界面或 API
```

### 2. Web 监控界面

```bash
# 启动 Flower 监控
celery -A spug flower --port=5555

# 访问 http://localhost:5555 查看：
# - 队列任务数
# - 失败任务列表
# - 死信队列状态
```

### 3. Prometheus监控对接（推荐）

使用celery-exporter对接Prometheus+Grafana实现实时监控：

```yaml
# docker-compose.yml
celery-exporter:
  image: danihodovic/celery-exporter:latest
  environment:
    - CELERY_BROKER_URL=amqp://user:pass@rabbitmq:5672/
    - CE_LOG_LEVEL=info
  ports:
    - "9808:9808"
```

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'celery'
    static_configs:
      - targets: ['celery-exporter:9808']
```

**关键监控指标**：

| 指标名 | 说明 | 告警阈值 |
|-------|------|---------|
| `celery_task_received_total` | 接收任务数 | - |
| `celery_task_succeeded_total` | 成功任务数 | - |
| `celery_task_failed_total` | 失败任务数 | > 0 |
| `celery_task_retried_total` | 重试任务数 | > 10/min |
| `celery_worker_up` | Worker存活状态 | = 0 |
| `celery_queue_messages` | 队列消息数 | > 100 |

### 4. 自定义监控脚本

```python
# apps/document/monitoring.py

from celery import current_app
from django.core.management.base import BaseCommand

class CheckDLQCommand(BaseCommand):
    """检查死信队列状态"""
    
    help = '检查资料库死信队列状态'
    
    def handle(self, *args, **options):
        inspector = current_app.control.inspect()
        
        # 获取所有队列信息
        queues = inspector.active_queues() or {}
        
        dlq_queues = []
        for worker, queue_list in queues.items():
            for queue in queue_list:
                if queue['name'].startswith('dlq.'):
                    dlq_queues.append(queue['name'])
        
        if not dlq_queues:
            self.stdout.write(self.style.SUCCESS('✅ 死信队列为空'))
            return
        
        self.stdout.write(self.style.WARNING(f'⚠️ 发现死信队列: {dlq_queues}'))
        
        # 发送告警（可选）
        for dlq in dlq_queues:
            self.send_alert(dlq)
    
    def send_alert(self, dlq_name):
        """发送告警通知"""
        # 集成企业微信/钉钉/邮件告警
        pass
```

---

## 死信队列处理流程

### 1. 发现失败任务

```
监控告警 → 发现 dlq.document.batch 有任务积压
                ↓
         查看 Flower 或日志
                ↓
         确认失败任务详情
```

### 2. 人工诊断

```bash
# 查看死信队列中的任务
rabbitmqctl list_queues name messages | grep dlq
# dlq.document.batch  5  ← 有5个失败任务

# 查看具体任务（通过日志）
tail -f /data/spug/spug_api/logs/celery.log | grep DLQ
```

### 3. 从DLQ消费并重试（完整示例）

```python
# apps/document/tasks/dlq_consumer.py

from kombu import Connection, Queue
from celery import current_app
from spug.celery import app as celery_app
import logging

logger = logging.getLogger(__name__)


def retry_dlq_tasks(queue_name, max_count=None):
    """
    消费DLQ中的消息并重新提交到业务队列
    
    Args:
        queue_name: 死信队列名称（如 'dlq.document.batch'）
        max_count: 最大处理数量（None表示处理全部）
    
    Returns:
        dict: {'success': 成功数, 'failed': 失败数}
    """
    result = {'success': 0, 'failed': 0}
    processed = 0
    
    with Connection(celery_app.conf.broker_url) as conn:
        simple_queue = conn.SimpleQueue(queue_name)
        
        while True:
            # 检查是否达到最大处理数
            if max_count and processed >= max_count:
                logger.info(f'[DLQ] 已达到最大处理数: {max_count}')
                break
            
            try:
                # 从DLQ获取一条消息（超时5秒）
                message = simple_queue.get(block=True, timeout=5)
            except conn.SimpleQueue.Empty:
                logger.info(f'[DLQ] 队列已空: {queue_name}')
                break
            
            try:
                # 解析消息体（Celery任务的序列化格式）
                task_payload = message.payload
                task_name = task_payload.get('headers', {}).get('task') or task_payload.get('task')
                args = task_payload.get('args', [])
                kwargs = task_payload.get('kwargs', {})
                task_id = task_payload.get('headers', {}).get('id') or task_payload.get('id')
                
                # 获取原队列名称
                original_queue = queue_name.replace('dlq.', '')
                
                logger.info(
                    f'[DLQ] 准备重试任务: task={task_name}, '
                    f'args={args}, target_queue={original_queue}'
                )
                
                # 重新提交到原业务队列，确保发送成功
                async_result = current_app.send_task(
                    task_name,
                    args=args,
                    kwargs=kwargs,
                    queue=original_queue,
                    headers={'x-retry-from-dlq': True, 'x-original-dlq-task-id': task_id}  # 标记为重试任务
                )
                
                # 只有拿到task_id，确认发送成功，才ACK DLQ消息
                if async_result.id:
                    message.ack()
                    # 同步更新失败日志状态
                    from django.db.models import F
                    TaskFailureLog.objects.filter(task_id=task_id).update(
                        status='retried',
                        updated_at=timezone.now(),
                        retry_count=F('retry_count') + 1
                    )
                    result['success'] += 1
                    logger.info(f'[DLQ] 重试成功: {task_name}, new_task_id={async_result.id}')
                else:
                    raise Exception('任务发送失败，未获取到有效task_id')
                
            except Exception as e:
                result['failed'] += 1
                logger.error(f'[DLQ] 重试失败: {e}', exc_info=True)
                # 发送失败，消息重新入队，等待下次处理，避免丢失
                message.reject(requeue=True)
            
            processed += 1
    
    logger.info(f'[DLQ] 处理完成: {result}')
    return result


# Django Command 封装
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = '重试死信队列中的任务'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'queue',
            type=str,
            help='死信队列名称（如 dlq.document.batch）'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=None,
            help='最大处理数量'
        )
    
    def handle(self, *args, **options):
        queue_name = options['queue']
        max_count = options['count']
        
        self.stdout.write(f'开始处理死信队列: {queue_name}')
        result = retry_dlq_tasks(queue_name, max_count)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'处理完成: 成功={result["success"]}, 失败={result["failed"]}'
            )
        )

# 使用示例：
# python manage.py retry_dlq dlq.document.batch --count=10
```

### 4. 失败原因持久化（数据库记录）

**问题**：队列消息可能过期或丢失，建议将失败信息持久化到数据库。

**模型设计**：

```python
# apps/document/models.py

from django.db import models
from django.utils import timezone


class TaskFailureLog(models.Model):
    """
    任务失败日志（持久化存储，不依赖消息队列）
    """
    STATUS_CHOICES = [
        ('retrying', '重试中'),      # 任务正在重试，非最终状态
        ('pending', '待处理'),        # 最终失败，需要人工处理
        ('retried', '已重试'),        # 已从DLQ重试
        ('discarded', '已丢弃'),      # 已丢弃
        ('resolved', '已解决'),       # 已解决
    ]
    
    task_id = models.CharField(max_length=255, unique=True, verbose_name='任务ID')
    task_name = models.CharField(max_length=255, verbose_name='任务名称')
    queue_name = models.CharField(max_length=255, verbose_name='队列名称')
    args = models.JSONField(default=list, verbose_name='位置参数')
    kwargs = models.JSONField(default=dict, verbose_name='关键字参数')
    
    failure_reason = models.TextField(verbose_name='失败原因')
    traceback = models.TextField(blank=True, verbose_name='错误堆栈')
    
    retry_count = models.IntegerField(default=0, verbose_name='重试次数')
    max_retries = models.IntegerField(default=3, verbose_name='最大重试次数')
    
    status = models.CharField(
        max_length=20, 
        default='pending',
        choices=STATUS_CHOICES,
        verbose_name='处理状态'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='解决时间')
    resolved_by = models.ForeignKey(
        'account.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='处理人'
    )
    
    class Meta:
        db_table = 'document_task_failure_logs'
        ordering = ['-created_at']
        verbose_name = '任务失败日志'
        verbose_name_plural = '任务失败日志'
    
    def __str__(self):
        return f'{self.task_name} - {self.status}'


# 在任务失败时记录
# apps/document/tasks/utils.py

def log_task_failure(task, exc, task_id, args, kwargs, einfo):
    """
    记录任务失败到数据库，重试中更新，仅最终失败标记为待处理
    """
    try:
        from django.db.models import F
        
        max_retries = task.max_retries if hasattr(task, 'max_retries') else 3
        current_retries = task.request.retries
        is_final_failure = current_retries >= max_retries

        # 唯一键更新，避免重复日志
        log, created = TaskFailureLog.objects.update_or_create(
            task_id=task_id,
            defaults={
                'task_name': task.name,
                'queue_name': task.request.delivery_info.get('routing_key', 'unknown'),
                'args': list(args),
                'kwargs': dict(kwargs),
                'failure_reason': str(exc),
                'traceback': einfo.traceback if einfo else '',
                'retry_count': current_retries,
                'max_retries': max_retries,
                'status': 'pending' if is_final_failure else 'retrying',
                'updated_at': timezone.now()
            }
        )
        if is_final_failure:
            logger.critical(f'[TaskFailureLog] 任务最终失败，已记录: {task_id}')
        else:
            logger.info(f'[TaskFailureLog] 任务重试中，已更新日志: {task_id}')

    except Exception as e:
        logger.error(f'[TaskFailureLog] 记录失败日志失败: {e}')
```

**管理界面**：

```python
# apps/document/admin.py

from django.contrib import admin
from .models import TaskFailureLog


@admin.register(TaskFailureLog)
class TaskFailureLogAdmin(admin.ModelAdmin):
    list_display = [
        'task_name', 'queue_name', 'status', 
        'retry_count', 'created_at', 'resolved_by'
    ]
    list_filter = ['status', 'queue_name', 'created_at']
    search_fields = ['task_id', 'task_name', 'failure_reason']
    readonly_fields = ['created_at', 'updated_at']
    
    actions = ['mark_as_retried', 'mark_as_discarded']
    
    def mark_as_retried(self, request, queryset):
        queryset.update(status='retried')
    mark_as_retried.short_description = '标记为已重试'
    
    def mark_as_discarded(self, request, queryset):
        queryset.update(status='discarded')
    mark_as_discarded.short_description = '标记为已丢弃'
```

### 4. 批量处理界面（可选）

```python
# views/admin/dlq_management.py

class DLQManagementView(View):
    """
    死信队列管理界面
    """
    
    @auth('admin.dlq.manage')
    def get(self, request):
        """获取死信队列列表"""
        dlq_list = [
            {
                'name': 'dlq.document.batch',
                'count': self._get_queue_count('dlq.document.batch'),
                'description': '批量操作失败任务'
            },
            {
                'name': 'dlq.document.merge',
                'count': self._get_queue_count('dlq.document.merge'),
                'description': '文件合并失败任务'
            },
            # ...
        ]
        return json_response(data=dlq_list)
    
    @auth('admin.dlq.manage')
    def post(self, request):
        """重试死信队列中的任务"""
        form = JsonParser(
            Argument('queue_name', required=True),
            Argument('action', required=True, help='retry/clear')
        ).parse(request.body)
        
        if form.action == 'retry':
            # 重试任务
            return self._retry_queue(form.queue_name)
        elif form.action == 'clear':
            # 清空队列（谨慎）
            return self._clear_queue(form.queue_name)
```

---

## 安全考虑

### 1. 权限控制

```python
# 只有管理员可以查看和操作死信队列
@auth('admin.dlq.view')
def get(self, request):
    ...

@auth('admin.dlq.manage')
def post(self, request):
    ...
```

### 2. 数据保护

```python
# 死信队列中的任务包含敏感信息，需要加密存储
# 或在一定时间后自动清理

CELERY_DLQ_RETENTION_DAYS = 7  # 保留7天
```

### 3. 监控告警

```python
# 死信队列积压时发送告警
# 【修改】只要有任务进入DLQ就立即告警（说明出现了自动化重试无法解决的问题）
DLQ_ALERT_THRESHOLD = 1  # 超过1个任务即告警
```

> **告警策略**：
> - `1`：只要有任务进入DLQ就告警（推荐，立即人工介入）
> - `5`：积压5个任务告警（适合高频任务场景）
> - `10`：积压10个任务告警（仅用于开发测试环境）

---

## 部署步骤

### 前置检查：队列迁移方案（重要！）

**问题**：若业务队列已在生产环境运行，直接添加 `x-dead-letter-exchange` 参数**不会生效**（RabbitMQ队列声明是幂等的，但参数变更需删除旧队列后重新创建）。

**解决方案**：

#### 方案A：低峰期操作（推荐）

适用于可以短暂暂停业务的场景：

```bash
# 1. 暂停业务队列的新任务提交（通过配置开关或网关限流）

# 2. 消费完旧队列中的所有消息
celery -A spug worker -Q document.batch -l info --pool=solo
# 等待队列为空...

# 3. 停止 Worker
pkill -f celery

# 4. 删除旧队列（RabbitMQ 管理界面或命令）
rabbitmqctl delete_queue document.batch

# 5. 更新配置，重启 Celery（自动创建带 DLX 参数的新队列）
celery -A spug worker -Q document.batch,document.merge,document.cleanup,document.folder.copy -l info
```

#### 方案B：平滑迁移（零停机）

适用于不能暂停业务的场景：

```python
# 1. 在 settings.py 中创建新队列（带 v2 后缀）
Queue(
    'document.batch.v2',  # ← 新队列
    routing_key='document.batch.v2',
    queue_arguments={
        'x-dead-letter-exchange': 'dlx',
        'x-dead-letter-routing-key': 'dlq.document.batch'
    }
)

# 2. 更新任务路由，新任务发送到 v2 队列
CELERY_TASK_ROUTES = {
    'apps.document.tasks.batch_delete_transfers': {'queue': 'document.batch.v2'},
    # ...
}

# 3. 同时启动两个 Worker：
# - 旧 Worker 继续消费 document.batch
# - 新 Worker 消费 document.batch.v2

# 4. 等待旧队列消费完毕
rabbitmqctl list_queues name messages | grep document.batch

# 5. 删除旧队列，路由统一指向 v2
```

---

### 步骤1：更新配置

```bash
# 修改 settings.py
vim spug_api/spug/settings.py

# 添加死信队列配置
```

### 步骤2：重启 Celery

```bash
# 停止现有 Worker
pkill -f celery

# ⚠️【严重】普通Worker只消费业务队列，不要消费死信队列！
# 死信队列应由人工或专门的管理脚本处理
celery -A spug worker -Q document.batch,document.merge,document.cleanup,document.folder.copy -l info
```

> **重要提示**：
> - ❌ **错误做法**：Worker 消费 `dlq.*` 队列（会导致死信任务被自动处理）
> - ✅ **正确做法**：Worker 只消费业务队列，死信队列由人工介入处理

### 步骤3：验证配置

```bash
# 查看队列是否正确创建
celery -A spug inspect active_queues

# 测试任务失败
# 提交一个会失败的任务，验证是否进入死信队列
```

### 步骤4：配置监控

```bash
# 启动 Flower
celery -A spug flower --port=5555

# 配置定时检查（crontab）
*/5 * * * * cd /data/spug/spug_api && python manage.py check_dlq
```

---

## 效果预期

### 优化前后对比

| 场景 | 优化前 | 优化后 |
|-----|--------|--------|
| 批量删除100个文件，第50个失败 | 前49个已删，后51个未删，无记录 | 任务进入DLQ，可查看哪些未删除 |
| 合并10GB文件失败 | 用户需重新上传 | 管理员修复后重试，用户无感知 |
| 磁盘满导致任务失败 | 任务丢失 | 任务在DLQ等待，扩容后重试 |

### 数据保护能力

```
┌─────────────────────────────────────────────────────────┐
│  死信队列配置前                                          │
│  失败任务 → 直接丢弃 → 数据丢失 → 用户投诉               │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│  死信队列配置后                                          │
│  失败任务 → 进入DLQ → 人工处理 → 数据恢复 → 用户满意      │
└─────────────────────────────────────────────────────────┘
```

---

## 回滚方案

如果配置出现问题，可以快速回滚：

```bash
# 1. 停止 Celery
pkill -f celery

# 2. 恢复旧配置
git checkout spug_api/spug/settings.py

# 3. 重启 Celery（使用旧配置）
celery -A spug worker -l info

# 4. 处理死信队列中的任务（如果有）
# 手动重试或清理
```

---

## 实现优先级

| 优先级 | 任务 | 预计工时 | 说明 |
|-------|------|---------|------|
| P0 | RabbitMQ 死信队列配置 | 4h | 核心功能 |
| P0 | 任务 max_retries 配置 | 2h | 所有异步任务 |
| P0 | 任务幂等性设计 | 4h | 防止重复处理 |
| P0 | 队列迁移方案（生产环境） | 2h | 避免数据丢失 |
| P1 | 监控脚本开发 | 3h | 检查队列状态 |
| P1 | Flower 监控部署 | 2h | Web 界面 |
| P1 | TaskFailureLog 模型 | 2h | 持久化失败信息 |
| P2 | DLQ 管理界面 | 4h | 可选功能 |
| P2 | 告警集成 | 2h | 企业微信/钉钉 |

---

## 测试验证

### 1. 死信队列基础功能测试

```python
# tests/test_dlq.py

import pytest
from celery import current_app
from apps.document.tasks import batch_delete_transfers


@pytest.mark.django_db
def test_task_retry_and_dlq():
    """测试任务重试3次后进入死信队列"""
    
    # 提交一个会失败的任务
    result = batch_delete_transfers.delay(
        transfer_ids=[99999],  # 不存在的ID
        request_user_id=1,
        request_tenant_id='test'
    )
    
    # 等待任务执行（使用测试模式）
    # 验证：任务被重试3次
    assert result.get(timeout=10, propagate=False) is None
    
    # 验证：任务最终进入死信队列
    # 检查 dlq.document.batch 队列是否有消息


def test_dlq_ttl_expiration():
    """测试死信队列消息7天后自动过期"""
    # 模拟消息在DLQ中存放7天
    # 验证：消息被自动清理
    pass
```

### 2. 幂等性测试

```python
@pytest.mark.django_db
def test_batch_delete_idempotency():
    """测试批量删除的幂等性"""
    
    # 创建测试数据
    transfer = DocumentTransfer.objects.create(...)
    
    # 第一次执行删除
    batch_delete_transfers.delay([transfer.id], 1, 'test').get()
    
    # 验证：记录已删除
    assert not DocumentTransfer.objects.filter(id=transfer.id).exists()
    
    # 第二次执行删除（重复）
    # 不应该报错，应该静默跳过
    result = batch_delete_transfers.delay([transfer.id], 1, 'test').get()
    
    # 验证：没有异常，正常完成
    assert result is not None
```

### 3. 并发安全测试

```python
@pytest.mark.django_db
def test_concurrent_merge_task():
    """测试并发提交合并任务（幂等性）"""
    
    import threading
    results = []
    
    def submit_merge():
        result = merge_file_chunks.delay(
            transfer_id=123,
            folder_id=1,
            file_name='test.txt',
            ...
        )
        results.append(result.id)
    
    # 同时提交10个相同的任务
    threads = [threading.Thread(target=submit_merge) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # 验证：只有一个Celery任务被创建（其他返回幂等响应）
    assert len(set(results)) == 1
```

### 4. 手动重试测试

```python
def test_manual_retry_from_dlq():
    """测试从死信队列手动重试"""
    
    # 1. 创建一个失败任务并进入DLQ
    # 2. 使用 retry_dlq_tasks 函数重试
    result = retry_dlq_tasks('dlq.document.batch', max_count=1)
    
    # 验证：任务被重新提交到业务队列
    assert result['success'] == 1
    assert result['failed'] == 0
```

### 5. Worker崩溃恢复测试

```python
def test_worker_crash_recovery():
    """测试Worker崩溃时任务不丢失（RabbitMQ持久化）"""
    
    # 1. 提交任务
    result = batch_delete_transfers.delay(...)
    
    # 2. 模拟Worker崩溃（kill -9）
    # 3. 重启Worker
    
    # 4. 验证：任务被重新消费并执行
    final_result = result.get(timeout=30)
    assert final_result is not None
```

### 测试检查清单

| 检查项 | 状态 |
|--------|------|
| 所有队列/交换机已显式配置durable=True持久化 | ☐ |
| 已开启CELERY_TASK_ACKS_LATE=True延迟ACK | ☐ |
| 已开启CELERY_TASK_REJECT_ON_WORKER_LOST=True | ☐ |
| 所有任务最终失败时会抛出异常，触发死信 | ☐ |
| Redis场景仅最终失败的任务会进入DLQ | ☐ |
| 存量队列已完成平滑迁移，无消息丢失风险 | ☐ |
| Worker仅消费业务队列，不监听DLQ | ☐ |
| 所有任务已配置幂等性逻辑和超时时间 | ☐ |
| 已完成DLQ功能、幂等性、容灾测试 | ☐ |
| 监控告警已配置，DLQ出现消息可及时通知 | ☐ |
| 回滚方案已验证，可快速恢复旧配置 | ☐ |

**功能测试**：
- [ ] 任务失败3次后进入DLQ
- [ ] 手动重试DLQ任务成功
- [ ] 任务幂等性（重复执行不影响数据）
- [ ] Worker崩溃时任务不丢失
- [ ] 死信队列TTL过期自动清理
- [ ] 并发提交相同任务只执行一次
- [ ] 告警通知正常发送

---

## 审查意见采纳说明

根据另一位架构师的审查意见，本方案已做以下优化：

| 审查意见 | 采纳情况 | 修改位置 |
|---------|---------|---------|
| **RabbitMQ持久化配置**（致命问题） | ✅ 采纳 | 所有队列/交换机添加 `durable=True` |
| **Celery延迟ACK配置**（致命问题） | ✅ 采纳 | 新增 `CELERY_TASK_ACKS_LATE=True` 等4项核心配置 |
| **任务重试逻辑**（致命问题） | ✅ 采纳 | 修正重试逻辑，最终失败必须抛出异常触发死信 |
| **Redis on_failure回调**（高严重） | ✅ 采纳 | 增加重试次数判断，仅最终失败进入DLQ |
| **Worker消费死信队列**（严重问题） | ✅ 采纳 | 修正启动命令，Worker只消费业务队列 |
| **TaskFailureLog写入逻辑**（重要） | ✅ 采纳 | 使用 `update_or_create` 唯一键更新，避免重复日志 |
| **DLQ重试工具**（重要） | ✅ 采纳 | 修正为先发送成功再ACK，失败时消息重新入队 |
| **任务超时配置**（重要） | ✅ 采纳 | 所有任务添加 `soft_time_limit` 和 `time_limit` |
| **任务幂等性设计** | ✅ 采纳 | 新增「任务幂等性设计」章节，提供完整示例 |
| **队列迁移方案** | ✅ 采纳 | 新增「前置检查：队列迁移方案」章节 |
| **配置统一管理** | ✅ 采纳 | 新增「配置统一管理」章节，集中管理DLQ配置 |
| **异常分类处理** | ✅ 采纳 | 新增「异常分类处理」章节，区分可重试/不可重试异常 |
| **Prometheus监控** | ✅ 采纳 | 新增「Prometheus监控对接」章节 |
| **DLQ消息处理流程** | ✅ 采纳 | 新增完整示例代码 `retry_dlq_tasks` |
| **失败原因持久化** | ✅ 采纳 | 新增 `TaskFailureLog` 模型和 Admin 界面 |
| **DLQ消息TTL** | ✅ 采纳 | 所有死信队列添加 `x-message-ttl: 7天` |
| **告警阈值调整** | ✅ 采纳 | 修改为 `DLQ_ALERT_THRESHOLD = 1` |
| **测试验证** | ✅ 采纳 | 新增「测试验证」章节，含5类测试用例 |

---

## 总结

死信队列是**生产环境必备**的可靠性保障机制：

| 价值 | 说明 |
|-----|------|
| **防丢数据** | 失败任务不丢失，可人工处理 |
| **便于排查** | 知道哪些任务失败了，失败原因 |
| **可恢复** | 支持手动重试，无需用户重新操作 |
| **提升可靠性** | 系统从"尽力而为"变为"可靠交付" |

**推荐立即实施，特别是生产环境**。
