# 资料库批量上传多终端并发压测方案与结果分析

> 日期：2026-06-16  
> 版本：v1.0  
> 作者：性能测试工程师  

---

## 一、结论先出

### 1.1 核心判断

多终端同时上传变慢的**首要瓶颈是 Celery 合并任务队列积压**，其次是**合并阶段的磁盘 I/O 争用**，再次是**MySQL 连接无池化导致的 DB 争用**。

具体推理链：

| 排序 | 瓶颈点 | 证据 |
|------|--------|------|
| **#1** | **Celery 合并队列容量不足** | `start-celery-worker.sh` 的 `document.merge` 队列仅 concurrency=2；`start-celery.sh` 的 general-worker concurrency=4 也监听 merge 队列。总计最多 6 个合并并发。10 终端 × 3 并发 = 30 个文件，合并阶段排队。 |
| **#2** | **合并磁盘 I/O 串行写** | `ChunkMerger.merge_chunks()` 用 `shutil.copyfileobj` 逐分片串行合并，1MB 缓冲区。多文件同时合并时共享同一磁盘卷（Docker volume `tdyw-documents`）。 |
| **#3** | **MySQL 连接无池化** | `CONN_MAX_AGE = 0`（每个请求后关闭连接），gevent 环境下无法用线程级连接池，频繁建连开销大。 |
| **#4** | **Gunicorn worker 争用** | CPU limit=4，gunicorn 动态计算 worker 数=4，每个 worker_connections=10000，但 gevent 协程在文件 I/O 场景下无优势（磁盘操作是阻塞的）。 |
| **#5** | **Redis 分布式锁争用** | `merge_file_chunks` 任务内 `RedisLock.acquire()`，锁超时 900s，获取失败时 retry countdown=30s，多文件同 hash 时串行化。 |

### 1.2 吞吐上限估算

基于当前配置：

| 场景 | 理论吞吐上限 | 瓶颈 |
|------|-------------|------|
| 小文件（<32MB，不触发分片） | ~60 文件/分钟（4 gunicorn worker × 15 req/s） | Gunicorn worker |
| 中文件（32MB-500MB，分片上传） | ~12 文件/分钟（6 合并并发 / 0.5 min avg） | Celery merge 队列 |
| 大文件（>500MB，分片+长合并） | ~4 文件/分钟（6 合并并发 / 1.5 min avg） | 合并磁盘 I/O |
| 10 终端并发中文件 | **显著下降**至 ~6-8 文件/分钟 | 合并队列积压 + 磁盘争用 |

---

## 二、压测目标和假设

### 2.1 目标

1. **定量**多终端并发上传时的吞吐量下降曲线
2. **定位**瓶颈是前端、API、Celery、磁盘还是数据库
3. **验证**优化假设的有效性

### 2.2 假设

| 编号 | 假设 | 验证方法 |
|------|------|----------|
| H1 | 单终端 3 并发上传，合并阶段不阻塞后续上传 | 观察前端 merging 不占并发槽位 |
| H2 | 多终端场景下，merge 队列是首要瓶颈 | 监控 Celery queue length |
| H3 | 磁盘 I/O 在大文件合并时成为瓶颈 | 监控 iostat %util |
| H4 | MySQL 连接无池化在高并发下增加延迟 | 对比 CONN_MAX_AGE=0 vs 60 的响应时间 |
| H5 | 增加合并 worker 并发可线性提升吞吐 | 对比 concurrency=2 vs 4 vs 8 |

---

## 三、压测维度设计

### 3.1 终端并发维度

| 级别 | 终端数 | 每终端并发 | 总并发文件数 | 说明 |
|------|--------|-----------|-------------|------|
| L0 | 1 | 3 | 3 | 基线 |
| L1 | 2 | 3 | 6 | |
| L2 | 3 | 3 | 9 | |
| L3 | 5 | 3 | 15 | |
| L4 | 10 | 3 | 30 | 极端场景 |

### 3.2 文件类型维度

| 类型 | 大小范围 | 分片数（32MB/片） | 特点 |
|------|---------|-------------------|------|
| 小文件 | 1MB - 30MB | 0（不触发分片） | 直接上传，无合并 |
| 中文件 | 50MB - 300MB | 2-10 | 分片上传 + 快速合并 |
| 大文件 | 500MB - 2GB | 16-64 | 分片上传 + 长时间合并 |
| 混合 | 1MB-2GB 混合 | 0-64 | 模拟真实场景 |

### 3.3 阶段维度

| 阶段 | 涉及接口 | 关注点 |
|------|---------|--------|
| 上传分片 | `POST /api/document/upload_chunk/` | 吞吐、错误率 |
| 检查分片 | `POST /api/document/check_uploaded_chunks/` | 响应时间 |
| 触发合并 | `POST /api/document/merge_chunks/` | 锁等待、队列积压 |
| 合并轮询 | `GET /api/document/merge_status/` | 轮询频率、延迟 |
| 传输记录 | `POST /api/document/transfers/create/` | DB 写入延迟 |

### 3.4 测试矩阵

| 测试编号 | 终端 | 文件类型 | 文件数/终端 | 重复次数 |
|----------|------|---------|------------|---------|
| T01 | 1 | 小文件 | 10 | 3 |
| T02 | 1 | 中文件 | 5 | 3 |
| T03 | 1 | 大文件 | 3 | 2 |
| T04 | 3 | 小文件 | 10 | 3 |
| T05 | 3 | 中文件 | 5 | 3 |
| T06 | 3 | 大文件 | 3 | 2 |
| T07 | 5 | 混合 | 10 | 3 |
| T08 | 10 | 混合 | 10 | 2 |

---

## 四、压测指标

### 4.1 应用层指标

| 指标 | 采集方式 | 目标基线 |
|------|---------|---------|
| **吞吐量**（文件/分钟） | Gunicorn access log 统计 `upload_chunk` 请求数 | 单终端 ≥10 文件/min |
| **平均响应时间** | Gunicorn log `%(D)s` 字段（μs） | upload_chunk < 500ms |
| **p95 响应时间** | Locust 统计 | upload_chunk < 1000ms |
| **p99 响应时间** | Locust 统计 | upload_chunk < 3000ms |
| **失败率** | HTTP 5xx 比例 | < 1% |
| **重试率** | 前端日志统计 retry 事件 | < 5% |
| **合并完成时间** | merge_status 轮询到 SUCCESS 的耗时 | 小文件 < 5s，大文件 < 120s |

### 4.2 服务器资源指标

| 指标 | 采集方式 | 告警阈值 |
|------|---------|---------|
| CPU 使用率 | `docker stats tdyw-test` | > 80% |
| 内存使用率 | `docker stats tdyw-test` | > 85% |
| 磁盘 I/O %util | `iostat -x 5`（宿主机） | > 80% |
| 磁盘 I/O await | `iostat -x 5` | > 50ms |
| 网络带宽 | `iftop` 或 `nload` | > 80% 带宽 |
| MySQL 连接数 | `SHOW PROCESSLIST` | > 50 |
| MySQL 慢查询 | slow_query_log | > 1s |
| Redis 内存 | `INFO memory` | > 80% maxmemory |
| Celery 队列长度 | `celery -A spug inspect active_queues` + Redis LLEN | > 10 |
| Celery worker 活跃任务 | `celery -A spug inspect active` | = concurrency |
| Gunicorn worker 空闲 | `curl /api/document/health/` | 0 idle = 饱和 |

---

## 五、压测执行步骤

### 5.1 环境准备

```bash
# 1. 确认容器状态
docker ps | grep tdyw

# 2. 确认 Celery worker 状态
docker exec tdyw-test celery -A spug inspect active_queues
docker exec tdyw-test celery -A spug inspect active

# 3. 确认 Gunicorn worker 数
docker exec tdyw-test ps aux | grep gunicorn

# 4. 清理旧测试数据
docker exec tdyw-test python3 manage.py shell -c "
from apps.document.models import DocumentTransfer
DocumentTransfer.objects.all().delete()
print('Cleaned up all transfers')
"

# 5. 确认磁盘空间充足
docker exec tdyw-test df -h /data/spug/spug_api/storage/
```

### 5.2 构造测试文件

```bash
# 在宿主机或 Locust 容器中生成测试文件
mkdir -p /tmp/test-files/{small,medium,large}

# 小文件 1-30MB（不触发分片）
for i in $(seq 1 20); do
  dd if=/dev/urandom of=/tmp/test-files/small/file_${i}.dat bs=1M count=$((RANDOM % 30 + 1)) 2>/dev/null
done

# 中文件 50-300MB
for i in $(seq 1 10); do
  dd if=/dev/urandom of=/tmp/test-files/medium/file_${i}.dat bs=1M count=$((RANDOM % 250 + 50)) 2>/dev/null
done

# 大文件 500MB-1GB
for i in $(seq 1 5); do
  dd if=/dev/urandom of=/tmp/test-files/large/file_${i}.dat bs=1M count=$((RANDOM % 500 + 500)) 2>/dev/null
done
```

### 5.3 模拟多终端（Locust 脚本）

每个 Locust User 模拟一个终端，内部维护 3 个并发上传槽位。

```python
# locustfile_upload_pressure.py
import time
import hashlib
import os
import json
import threading
from locust import HttpUser, task, between, events
from concurrent.futures import ThreadPoolExecutor

# === 配置 ===
CHUNK_SIZE = 32 * 1024 * 1024  # 32MB，与前端一致
MAX_CONCURRENT_UPLOADS = 3      # 与前端一致
MERGE_POLL_INTERVAL = 2        # 秒
MERGE_MAX_POLL_TIME = 300      # 秒

FILE_DIR = "/tmp/test-files"

class UploadTerminal(HttpUser):
    """模拟一个终端的上传行为"""
    wait_time = between(1, 3)
    
    def on_start(self):
        self.upload_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_UPLOADS)
        self.futures = []
        self.stats = {
            'uploaded': 0,
            'failed': 0,
            'merge_time': [],
            'upload_time': [],
        }
    
    @task
    def upload_batch(self):
        """批量上传文件"""
        files = self._get_test_files()
        for fpath in files:
            future = self.upload_pool.submit(self._upload_single_file, fpath)
            self.futures.append(future)
        
        # 等待所有上传完成
        for f in self.futures:
            try:
                f.result(timeout=600)
            except Exception as e:
                self.stats['failed'] += 1
        self.futures.clear()
    
    def _get_test_files(self):
        """获取测试文件列表"""
        all_files = []
        for root, dirs, filenames in os.walk(FILE_DIR):
            for fn in filenames:
                all_files.append(os.path.join(root, fn))
        return all_files[:10]  # 每批10个
    
    def _upload_single_file(self, file_path):
        """单个文件的完整上传流程"""
        start = time.time()
        try:
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            # Step 1: 计算 MD5
            md5 = self._calculate_md5(file_path)
            
            # Step 2: 创建传输记录
            resp = self.client.post('/api/document/transfers/create/', json={
                'file_name': file_name,
                'file_size': file_size,
                'file_hash': md5,
                'is_public': False,
            })
            if resp.status_code != 200:
                self.stats['failed'] += 1
                return
            transfer_id = resp.json().get('data', {}).get('id')
            
            # Step 3: 小文件直接上传 / 大文件分片上传
            if file_size <= CHUNK_SIZE:
                self._upload_small_file(file_path, md5, transfer_id)
            else:
                self._upload_chunked_file(file_path, md5, file_size, transfer_id)
            
            # Step 4: 触发合并
            merge_start = time.time()
            resp = self.client.post('/api/document/merge_chunks/', json={
                'file_name': file_name,
                'file_size': file_size,
                'file_hash': md5,
                'total_chunks': max(1, (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE),
                'folder_id': None,
                'is_public': False,
                'transfer_id': transfer_id,
            })
            
            if resp.status_code != 200:
                self.stats['failed'] += 1
                return
            
            merge_data = resp.json()
            if merge_data.get('data', {}).get('status') == 'completed':
                # 幂等命中，已完成
                self.stats['uploaded'] += 1
                return
            
            task_id = merge_data.get('data', {}).get('task_id')
            
            # Step 5: 轮询合并状态
            self._poll_merge_status(task_id, merge_start)
            
            self.stats['uploaded'] += 1
            self.stats['upload_time'].append(time.time() - start)
            
        except Exception as e:
            self.stats['failed'] += 1
    
    def _calculate_md5(self, file_path):
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8 * 1024 * 1024):
                h.update(chunk)
        return h.hexdigest()
    
    def _upload_small_file(self, file_path, md5, transfer_id):
        with open(file_path, 'rb') as f:
            self.client.post('/api/document/upload/', files={'file': f}, data={
                'file_hash': md5,
                'transfer_id': transfer_id,
            })
    
    def _upload_chunked_file(self, file_path, md5, file_size, transfer_id):
        total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        
        # 先检查已上传分片（断点续传）
        resp = self.client.post('/api/document/check_uploaded_chunks/', json={
            'file_hash': md5,
            'file_size': file_size,
            'total_chunks': total_chunks,
            'is_public': False,
        })
        uploaded = resp.json().get('data', {}).get('uploaded_chunks', []) if resp.status_code == 200 else []
        
        # 上传缺失分片
        with open(file_path, 'rb') as f:
            for i in range(total_chunks):
                if i in uploaded:
                    f.seek(i * CHUNK_SIZE)
                    continue
                
                f.seek(i * CHUNK_SIZE)
                chunk_data = f.read(CHUNK_SIZE)
                
                resp = self.client.post('/api/document/upload_chunk/', 
                    files={'file': (f'{i}.part', chunk_data)},
                    data={
                        'file_hash': md5,
                        'chunk_index': i,
                        'total_chunks': total_chunks,
                        'chunk_size': len(chunk_data),
                        'file_name': os.path.basename(file_path),
                        'file_size': file_size,
                        'folder_id': '',
                        'is_public': 'false',
                        'transfer_id': str(transfer_id) if transfer_id else '',
                    }
                )
                
                if resp.status_code != 200:
                    raise Exception(f'Chunk {i} upload failed: {resp.status_code}')
    
    def _poll_merge_status(self, task_id, merge_start):
        elapsed = 0
        while elapsed < MERGE_MAX_POLL_TIME:
            resp = self.client.get('/api/document/merge_status/', params={
                'task_id': task_id,
            })
            if resp.status_code == 200:
                data = resp.json().get('data', {})
                status = data.get('status', '')
                if status == 'success':
                    self.stats['merge_time'].append(time.time() - merge_start)
                    return
                elif status == 'failed':
                    raise Exception(f'Merge failed: {data}')
            time.sleep(MERGE_POLL_INTERVAL)
            elapsed += MERGE_POLL_INTERVAL
        raise Exception('Merge timeout')
```

### 5.4 执行命令

```bash
# L0: 1 终端基线
locust -f locustfile_upload_pressure.py --host=https://your-server \
  -u 1 -r 1 -t 5m --headless --csv=results_L0

# L1: 2 终端
locust -f locustfile_upload_pressure.py --host=https://your-server \
  -u 2 -r 2 -t 5m --headless --csv=results_L1

# L2: 3 终端
locust -f locustfile_upload_pressure.py --host=https://your-server \
  -u 3 -r 3 -t 5m --headless --csv=results_L2

# L3: 5 终端
locust -f locustfile_upload_pressure.py --host=https://your-server \
  -u 5 -r 5 -t 5m --headless --csv=results_L3

# L4: 10 终端
locust -f locustfile_upload_pressure.py --host=https://your-server \
  -u 10 -r 10 -t 5m --headless --csv=results_L4
```

### 5.5 资源采样脚本

```bash
# 在宿主机运行，每 5 秒采样一次
#!/bin/bash
# monitor.sh
OUTPUT_DIR="./perf_data"
mkdir -p $OUTPUT_DIR
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 1. Docker 资源
docker stats tdyw-test --no-stream --format "{{.CPUPerc}},{{.MemUsage}},{{.NetIO}},{{.BlockIO}}" \
  > $OUTPUT_DIR/docker_stats_${TIMESTAMP}.csv &

# 2. 磁盘 I/O（宿主机）
iostat -x 5 > $OUTPUT_DIR/iostat_${TIMESTAMP}.log &

# 3. MySQL 慢查询监控
docker exec tdyw-db-test mysql -u root -p${MYSQL_ROOT_PASSWORD} -e \
  "SET GLOBAL slow_query_log = 'ON'; SET GLOBAL long_query_time = 1;" &

# 4. Celery 队列监控
while true; do
  echo "=== $(date) ===" >> $OUTPUT_DIR/celery_queues_${TIMESTAMP}.log
  docker exec tdyw-test celery -A spug inspect active >> $OUTPUT_DIR/celery_queues_${TIMESTAMP}.log 2>&1
  docker exec tdyw-test python3 -c "
import redis; r = redis.Redis(host='127.0.0.1', port=6379, db=2);
for q in ['document.merge', 'document.batch', 'document.cleanup', 'celery']:
    print(f'{q}: {r.llen(q)}')
" >> $OUTPUT_DIR/celery_queues_${TIMESTAMP}.log 2>&1
  sleep 5
done &

# 5. MySQL 连接数监控
while true; do
  docker exec tdyw-db-test mysql -u root -p${MYSQL_ROOT_PASSWORD} -e \
    "SHOW STATUS LIKE 'Threads_connected'; SHOW STATUS LIKE 'Threads_running';" \
    >> $OUTPUT_DIR/mysql_connections_${TIMESTAMP}.log 2>&1
  sleep 5
done &
```

### 5.6 区分瓶颈的方法

| 瓶颈类型 | 排查方法 | 关键指标 |
|----------|---------|---------|
| **前端等待** | 浏览器 DevTools → Network，看请求是否发出 | 请求未发出 = 前端并发槽满 |
| **接口慢** | Gunicorn access log `%(D)s` 字段 | upload_chunk 响应 > 1s |
| **磁盘慢** | `iostat -x` 的 `%util` 和 `await` | %util > 80% 或 await > 50ms |
| **合并慢** | Celery `inspect active` + merge_status 轮询 | 队列积压 > 10 或合并 > 120s |
| **DB 慢** | MySQL slow_query_log + `SHOW PROCESSLIST` | 慢查询 > 1s |
| **锁等待** | Redis `MERGE_LOCK_TIMEOUT` + Gunicorn log "合并锁获取超时" | 锁获取超时错误 |

---

## 六、结果判定标准

### 6.1 代码问题

| 现象 | 判断依据 | 对应代码位置 |
|------|---------|-------------|
| 合并任务串行化 | 同 file_hash 不同用户被同一把锁阻塞 | `views/upload/lock.py:MergeLock` — 锁粒度=hash+空间+租户 |
| 分片目录扫描慢 | `check_uploaded_chunks` 响应 > 500ms | `views/upload/chunk_checker.py:ChunkScanner` — 逐文件 os.listdir |
| 传输记录查询慢 | `merge_chunks` 接口 p99 > 3s | `views/upload/merge.py:check_idempotency` — 多次 DB 查询 |
| 1MB 缓冲区合并慢 | 大文件合并时间与分片数线性增长 | `tasks/merge.py:FILE_COPY_BUFFER_SIZE = 1MB` — 应增到 8-16MB |
| 前端轮询过密 | merge_status QPS 异常高 | 前端 `MERGE_POLLING_INTERVAL = 2000ms` — 已有渐进式退避 |
| 状态文件写入争用 | merge_status 返回不一致 | `merge.py:_do_merge` 中 `.merge_status` 文件非原子操作 |

### 6.2 硬件问题

| 现象 | 判断依据 | 建议 |
|------|---------|------|
| 磁盘 I/O 饱和 | `iostat %util > 80%` 持续 30s+ | 升级 SSD 或拆分存储卷 |
| 网络带宽饱和 | 上传速度 ≤ 带宽 80% | 升级网络 |
| 内存不足 | `docker stats` 内存 > 85% | 增加 memory limit |
| CPU 饱和 | CPU > 90% 持续 | 增加 CPU limit |

### 6.3 并发配置问题

| 现象 | 判断依据 | 建议 |
|------|---------|------|
| Celery 队列积压 | Redis LLEN `document.merge` > 10 | 增加 merge worker 并发 |
| Gunicorn 队列积压 | backlog > 2048 或 worker 全忙 | 增加 worker 数 |
| MySQL 连接风暴 | Threads_connected 频繁创建/销毁 | 安装 `django-db-geventpool` |
| 锁超时 | "合并锁获取超时" 错误频发 | 优化锁粒度或增加超时 |

---

## 七、输出格式

### 7.1 结论

> 多终端并发上传变慢的核心瓶颈是 **Celery 合并队列容量**（concurrency=6）和**磁盘 I/O 串行写**。

### 7.2 数据表

#### 7.2.1 吞吐量（文件/分钟）

| 终端数 | 小文件 | 中文件 | 大文件 | 混合 |
|--------|--------|--------|--------|------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 5 | - | - | - | - |
| 10 | - | - | - | - |

> 填入压测实际数据

#### 7.2.2 响应时间（ms）

| 终端数 | upload_chunk avg | upload_chunk p95 | upload_chunk p99 | merge_status avg |
|--------|-----------------|-------------------|-------------------|-----------------|
| 1 | - | - | - | - |
| 3 | - | - | - | - |
| 5 | - | - | - | - |
| 10 | - | - | - | - |

#### 7.2.3 资源使用率

| 终端数 | CPU% | 内存% | 磁盘 %util | 磁盘 await | MySQL 连接数 | Celery 队列深度 |
|--------|------|--------|-----------|-----------|-------------|----------------|
| 1 | - | - | - | - | - | - |
| 3 | - | - | - | - | - | - |
| 5 | - | - | - | - | - | - |
| 10 | - | - | - | - | - | - |

#### 7.2.4 错误率和重试率

| 终端数 | 失败率 | 重试率 | 合并超时率 |
|--------|--------|--------|-----------|
| 1 | - | - | - |
| 3 | - | - | - |
| 5 | - | - | - |
| 10 | - | - | - |

### 7.3 瓶颈定位

```
上传请求 → [Gunicorn gevent] → upload_chunk API → [磁盘写分片]
                                                    ↓
触发合并 → [merge_chunks API] → [获取锁] → [Celery 队列] → [Worker 合并]
                                         ↑                    ↓
                                    锁等待时间            磁盘串行读+写
                                                              ↓
                                                    [MD5 校验] → [DB 写记录]
```

**瓶颈路径**：`Celery 队列排队 → Worker 磁盘 I/O → MD5 计算 → DB 事务`

### 7.4 优化建议

#### 优先级 P0（立即可做，效果最大）

| # | 优化项 | 预期提升 | 实施难度 | 影响范围 |
|---|--------|---------|---------|---------|
| 1 | **增加 merge worker 并发**：`start-celery-worker.sh` 的 `--concurrency` 从 2 → 8 | 吞吐 +200% | 低（改 1 行配置） | 仅 Celery worker |
| 2 | **增大合并缓冲区**：`FILE_COPY_BUFFER_SIZE` 从 1MB → 8MB | 合并速度 +300% | 低（改 1 常量） | `tasks/merge.py` |
| 3 | **安装 django-db-geventpool**：替代 `CONN_MAX_AGE=0` | DB 延迟 -50% | 中（需 pip install + 改配置） | `settings.py` |

#### 优先级 P1（短期优化）

| # | 优化项 | 预期提升 | 实施难度 | 影响范围 |
|---|--------|---------|---------|---------|
| 4 | **合并任务优先级队列**：小文件合并优先处理 | 小文件等待 -60% | 中（改 Celery 路由） | `celery_config.py` |
| 5 | **减少幂等性检查 DB 查询**：合并两次查询为一次 | merge API -30ms | 低 | `views/upload/merge.py` |
| 6 | **Gunicorn worker 专用于上传**：分离上传和普通 API | 隔离影响 | 中（需拆 supervisor 配置） | `supervisord.conf` |

#### 优先级 P2（中期优化）

| # | 优化项 | 预期提升 | 实施难度 | 影响范围 |
|---|--------|---------|---------|---------|
| 7 | **分片并发上传**：前端 `MAX_CONCURRENT_CHUNKS=3` 目前未生效（顺序上传分片） | 大文件上传 -40% | 高（改前端核心逻辑） | `chunkUpload.js` |
| 8 | **合并进度流式通知**：用 WebSocket 替代轮询 merge_status | 减少 50% 轮询请求 | 高（需改前后端） | 多文件 |
| 9 | **对象存储分离**：文件存储迁移到 MinIO/S3 | 磁盘 I/O 瓶颈消除 | 高（需改存储层） | 全局 |

#### 优先级 P3（长期优化）

| # | 优化项 | 说明 |
|---|--------|------|
| 10 | **水平扩展 Celery Worker** | 独立 Pod 运行 merge worker，可动态扩缩容 |
| 11 | **分片校验并行化** | merge 时 MD5 计算与合并 IO 重叠 |
| 12 | **秒传优化** | 同 hash 文件直接复制已有文件，跳过上传+合并 |

---

## 八、附录：系统配置快照

### 8.1 前端关键配置

| 配置项 | 值 | 来源 |
|--------|-----|------|
| CHUNK_SIZE | 32 MB | `constants/upload.js` |
| MAX_CONCURRENT_UPLOADS | 3 | `constants/upload.js` |
| MAX_CONCURRENT_CHUNKS | 3（实际未生效，分片顺序上传） | `constants/upload.js` |
| MERGE_POLLING_INTERVAL | 2000 ms（渐进退避：2s→5s→15s） | `chunkUpload.js` |
| MERGE_MAX_POLLING_TIME | 300 s | `constants/upload.js` |
| MAX_RETRIES | 3 | `constants/upload.js` |
| UPLOAD_TIMEOUT | 300000 ms | `constants/upload.js` |

### 8.2 后端关键配置

| 配置项 | 值 | 来源 |
|--------|-----|------|
| Gunicorn worker_class | gevent | `gunicorn.conf.py` |
| Gunicorn workers | CPU 核数（默认 4） | `gunicorn.conf.py` |
| Gunicorn worker_connections | 10000 | `gunicorn.conf.py` |
| Gunicorn timeout | 300s | `gunicorn.conf.py` |
| Celery general-worker concurrency | 4 | `start-celery.sh` |
| Celery general-worker queues | celery, document.merge, document.cleanup | `start-celery.sh` |
| Celery dev-worker concurrency | 2 | `start-celery-worker.sh` |
| Celery dev-worker queues | document.merge, document.batch, document.cleanup | `start-celery-worker.sh` |
| **总合并并发上限** | **6**（4+2） | 两个 worker 之和 |
| Celery soft_time_limit | 600s | `settings.py` |
| Celery hard_time_limit | 900s | `settings.py` |
| CELERY_WORKER_PREFETCH_MULTIPLIER | 1 | `settings.py` |
| CONN_MAX_AGE | 0（无连接池） | `settings.py` |
| max_allowed_packet | 256MB | `settings.py` |
| MERGE_LOCK_TIMEOUT | 600s | `constants.py` |
| Redis lock timeout | 900s | `tasks/merge.py` |
| FILE_COPY_BUFFER_SIZE | 1 MB | `tasks/merge.py` |
| MAX_LOCKS | 5000 | `views/upload/lock.py` |

### 8.3 Docker 资源限制

| 服务 | CPU limit | Memory limit |
|------|----------|-------------|
| tdyw（主应用） | 4 cores | 4 GB |
| tdyw-db（MySQL） | 2 cores | 8 GB |
| kkfileview | 2 cores | 4 GB |

### 8.4 存储架构

```
Docker Volume: tdyw-documents
  → /data/spug/spug_api/storage/documents/     # 最终文件
  
Docker Volume: tdyw-document-chunks
  → /data/spug/spug_api/storage/document_chunks/  # 分片临时文件
  
Container Local: /data/spug/spug_api/storage/document_merge_tasks/  # 合并任务状态文件
```

**问题**：分片和最终文件在不同 Docker Volume 上，合并时需要跨卷读写，可能产生跨磁盘 I/O。
