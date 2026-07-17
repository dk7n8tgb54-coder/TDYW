# 资料库性能测试指南

## 📋 测试脚本清单

| 脚本名 | 测试场景 | 端口 | 权重 |
|--------|---------|------|------|
| `locustfile_document.py` | 基础功能压测 | 8089 | P0 |
| `locustfile_recycle_bin.py` | 回收站专项 | 8091 | P0 |
| `locustfile_pagination.py` | 分页功能 | 8092 | P0 |
| `locustfile_folder_depth.py` | 深度嵌套 | 8093 | P1 |
| `run_all_stress_tests.py` | 一键全量测试 | - | - |

---

## 🚀 快速开始

### 1. 单个测试运行

```bash
# 基础功能压测（交互式）
locust -f locustfile_document.py -H http://localhost

# 回收站压测
locust -f locustfile_recycle_bin.py -H http://localhost --web-port 8091

# 分页压测
locust -f locustfile_pagination.py -H http://localhost --web-port 8092

# 深度嵌套压测
locust -f locustfile_folder_depth.py -H http://localhost --web-port 8093
```

### 2. 命令行模式（无头模式）

```bash
# 基础压测（50用户，5分钟）
locust -f locustfile_document.py -H http://localhost \
       --users 50 --spawn-rate 10 --run-time 5m --headless \
       --csv=document_test

# 高强度压测（200用户，10分钟）
locust -f locustfile_document.py -H http://localhost \
       --users 200 --spawn-rate 50 --run-time 10m --headless \
       --csv=document_stress
```

### 3. 一键全量测试

```bash
# 运行所有测试（默认50用户，5分钟）
python run_all_stress_tests.py

# 自定义参数
python run_all_stress_tests.py \
    --host http://192.168.1.100 \
    --users 100 \
    --time 10m \
    --output ./reports
```

---

## 📊 测试场景详解

### 1️⃣ 基础功能压测 (`locustfile_document.py`)

**覆盖场景**:
- ✅ 高频查询（文件夹列表、搜索、磁盘使用）
- ✅ 文件夹CRUD（创建、重命名、移动、复制）
- ✅ 文件操作（上传、重命名、移动、复制、删除）
- ✅ 分片上传（创建传输、更新进度、完成传输）
- ✅ 合并锁竞争（相同Hash并发合并）
- ✅ 公共空间专项（CRUD、权限、合并锁）

**关键指标**:
| 指标 | 目标值 | 警告值 |
|------|--------|--------|
| 平均响应时间 | <100ms | >200ms |
| P95响应时间 | <300ms | >500ms |
| 失败率 | <0.1% | >1% |
| 吞吐量 | >10 req/s | <5 req/s |

---

### 2️⃣ 回收站压测 (`locustfile_recycle_bin.py`)

**覆盖场景**:
- ✅ 大容量列表查询（1000+已删除文件）
- ✅ 回收站搜索性能
- ✅ 统计信息计算（磁盘占用）
- ✅ 恢复竞争（多用户恢复同一资源）
- ✅ 批量永久删除（Celery异步任务）
- ✅ 空间视图切换（私有/公共/全部）

**关键指标**:
| 指标 | 目标值 | 警告值 |
|------|--------|--------|
| 列表加载时间 | <500ms | >1000ms |
| 搜索响应时间 | <1000ms | >2000ms |
| 统计计算时间 | <300ms | >500ms |
| 恢复成功率 | >99% | <95% |

---

### 3️⃣ 分页压测 (`locustfile_pagination.py`)

**覆盖场景**:
- ✅ 真实分页加载（验证后端分页）
- ✅ 翻页操作（上一页/下一页/跳转）
- ✅ 分页大小切换（10/20/50/100）
- ✅ 深度分页（第50/100/200/500页）
- ✅ 并发多页码访问
- ✅ 排序+分页组合

**关键指标**:
| 指标 | 目标值 | 警告值 |
|------|--------|--------|
| 分页响应时间 | <200ms | >500ms |
| 深度分页(P100) | <500ms | >1000ms |
| 数据一致性 | 100% | <100% |
| 翻页流畅性 | 无卡顿 | 明显延迟 |

**常见问题**:
```
问题: OFFSET深度分页慢
症状: 第1000页加载很慢
解决: 使用游标分页（cursor-based）

问题: 数据重复/遗漏
症状: 翻页时看到重复数据
解决: 使用稳定排序键
```

---

### 4️⃣ 深度嵌套压测 (`locustfile_folder_depth.py`)

**覆盖场景**:
- ✅ 深层嵌套创建（测试深度限制）
- ✅ 深层路径CRUD操作
- ✅ 深层文件上传
- ✅ 递归获取文件夹树
- ✅ 极限深度测试（50层）
- ✅ 深层移动/复制/删除

**关键指标**:
| 指标 | 目标值 | 警告值 |
|------|--------|--------|
| 递归查询时间 | <1000ms | >3000ms |
| 最大支持深度 | >20层 | <10层 |
| 递归删除性能 | O(n) | O(n²) |
| 内存占用 | <100MB | >500MB |

---

## 🔍 监控指标

### 应用层监控

```bash
# 1. 响应时间分布
- P50 (中位数)
- P95 (95%分位)
- P99 (99%分位)
- Max (最大值)

# 2. 吞吐量
- Requests/sec
- Failures/sec

# 3. 错误率
- 失败率 < 1%
- 错误类型分布
```

### 数据库监控

```sql
-- 1. 慢查询监控
SELECT * FROM mysql.slow_log 
WHERE query_time > 0.5 
ORDER BY query_time DESC;

-- 2. 连接数监控
SHOW STATUS LIKE 'Threads_connected';
SHOW STATUS LIKE 'Max_used_connections';

-- 3. 锁等待监控
SHOW ENGINE INNODB STATUS;
```

### 系统监控

```bash
# 1. CPU和内存
top -p $(pgrep -d',' python)

# 2. 磁盘IO
iostat -x 1

# 3. 网络连接
netstat -an | grep :8000 | wc -l

# 4. Celery队列
redis-cli LLEN celery
```

---

## ⚠️ 常见问题排查

### 问题1: 大量连接超时
```
症状: 大量 requests.Timeout 错误
原因: 数据库连接池耗尽
解决: 
  1. 增加 DATABASE_OPTIONS['MAX_CONNS']
  2. 启用连接池复用
  3. 优化慢查询
```

### 问题2: 内存持续增长
```
症状: 内存使用不断上涨，最终OOM
原因: 查询结果集过大未释放
解决:
  1. 添加查询LIMIT限制
  2. 使用迭代器处理大数据集
  3. 检查是否有内存泄漏
```

### 问题3: 数据库死锁
```
症状: 大量 Lock wait timeout 错误
原因: 并发更新同一行数据
解决:
  1. 减少事务范围
  2. 按固定顺序获取锁
  3. 使用乐观锁替代
```

### 问题4: Celery任务堆积
```
症状: 异步任务响应慢，队列积压
原因: Worker数量不足或任务执行慢
解决:
  1. 增加Celery Worker数量
  2. 优化任务执行逻辑
  3. 启用任务优先级
```

---

## 📈 性能基线

### 推荐配置下的性能指标

**硬件配置**:
- CPU: 4核
- 内存: 8GB
- 数据库: MySQL 8.0
- 缓存: Redis 6.x

**性能基线**:
| 场景 | 并发用户 | 平均响应 | P95响应 | 吞吐量 | 失败率 |
|------|---------|---------|---------|--------|--------|
| 列表查询 | 50 | 50ms | 150ms | 20 rps | 0% |
| 文件上传 | 20 | 200ms | 500ms | 10 rps | 0% |
| 分片合并 | 10 | 100ms | 300ms | 5 rps | <1% |
| 回收站列表 | 50 | 200ms | 500ms | 15 rps | 0% |
| 深度分页 | 20 | 100ms | 300ms | 10 rps | 0% |

---

## 🛠️ 优化建议

### 数据库优化
```sql
-- 1. 添加必要索引
ALTER TABLE spug_document_file ADD INDEX idx_folder_id (folder_id);
ALTER TABLE spug_document_file ADD INDEX idx_created_by (created_by_id);

-- 2. 优化慢查询
-- 使用 EXPLAIN 分析查询计划
EXPLAIN SELECT * FROM spug_document_file WHERE folder_id = 123;

-- 3. 定期维护
OPTIMIZE TABLE spug_document_file;
ANALYZE TABLE spug_document_file;
```

### 缓存优化
```python
# 1. 列表缓存
@cache_page(60)  # 缓存1分钟
def get_folder_list(request):
    ...

# 2. 统计信息缓存
from django.core.cache import cache

def get_disk_usage(user_id):
    cache_key = f"disk_usage:{user_id}"
    result = cache.get(cache_key)
    if not result:
        result = calculate_disk_usage(user_id)
        cache.set(cache_key, result, 300)  # 缓存5分钟
    return result
```

### 异步优化
```python
# 大文件合并改为异步
@shared_task
def merge_large_file(transfer_id):
    ...

# 批量删除改为异步
@shared_task
def batch_delete_files(file_ids):
    ...
```

---

## 📝 测试报告解读

### Locust CSV文件说明

| 文件名 | 说明 |
|--------|------|
| `_stats.csv` | 统计摘要（关键指标） |
| `_stats_history.csv` | 历史统计（时序数据） |
| `_failures.csv` | 失败详情 |
| `_exceptions.csv` | 异常详情 |

### 关键指标解读

```csv
# _stats.csv 示例
Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%
GET,/api/document/folder/,1000,0,50,55,20,200,1024,20.5,0,50,60,70,80,100,150,180,200,200,200,200
```

**关键字段**:
- `Request Count`: 总请求数
- `Failure Count`: 失败数
- `Median Response Time`: 中位数响应时间（P50）
- `90%`: P90响应时间
- `95%`: P95响应时间
- `Requests/s`: 每秒请求数（吞吐量）

---

## 🔗 相关文档

- [Locust官方文档](https://docs.locust.io/)
- [Django性能优化](https://docs.djangoproject.com/en/4.2/topics/performance/)
- [MySQL性能调优](https://dev.mysql.com/doc/refman/8.0/en/optimization.html)

---

**最后更新**: 2024年

如有问题，请联系开发团队。
