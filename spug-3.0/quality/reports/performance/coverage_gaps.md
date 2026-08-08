# Performance Testing Coverage Gaps

## 未执行场景

### 1. Locust 负载测试
- **原因**：Locust 未安装在本地环境
- **影响**：无法测量并发负载下的吞吐量、P95/P99 和错误率
- **后续**：安装 Locust，在独立测试环境中执行

### 2. 写入压测
- **原因**：tdyw-test 连接 dev 数据库 (spug)，写入会影响开发数据
- **影响**：无法测量 POST/PUT/DELETE 操作的性能
- **后续**：创建独立 test_spug 数据库

### 3. 峰值负载测试
- **原因**：dev 数据库不安全，无法承受高并发
- **影响**：无法确定系统最大容量
- **后续**：在独立测试环境中逐步加压

### 4. 持续稳定性测试 (Soak)
- **原因**：dev 数据库不安全，长时间运行可能影响开发
- **影响**：无法检测内存泄漏、连接泄漏
- **后续**：在独立测试环境中运行 30 分钟以上

### 5. 文件上传/下载测试
- **原因**：需要 ALLOW_WRITE_LOAD=true 和测试数据库
- **影响**：无法测量文件 I/O 性能
- **后续**：在独立测试环境中使用安全样本文件

## 未覆盖端点

| 端点 | 原因 | 正确路径 |
|------|------|---------|
| GET /api/fault/records/ | 路径错误 | /api/fault/faultrecord/ |
| GET /api/document/file/ | 返回 405 | 需确认请求方式 |
| GET /api/device/device-history/ | 路径未确认 | 需检查 device app urls.py |
| POST /api/account/login/ (token refresh) | 未测试 token 刷新 | N/A |
| 所有 POST/PUT/PATCH/DELETE | 未执行写入测试 | 需独立测试环境 |

## 未测量指标

1. **并发吞吐量 (RPS)**：单请求探测无法测量
2. **并发 P95/P99**：需要 Locust 负载测试
3. **数据库连接数趋势**：需要在负载下监控
4. **Redis 缓存命中率**：未启用 Redis 监控
5. **Celery 队列深度**：无活跃任务
6. **容器 CPU/内存趋势**：单请求负载过低
7. **慢查询日志**：未启用 MariaDB slow_query_log
8. **EXPLAIN 分析**：未在容器内执行
9. **磁盘 I/O**：未监控
10. **网络延迟基线**：WSL 网络层可能影响测量

## 建议补充项

1. 在独立测试环境中安装 Locust 并执行所有场景
2. 启用 MariaDB slow_query_log（long_query_time=0.5）
3. 使用 Redis INFO command 监控缓存命中率
4. 使用 docker stats 监控容器资源
5. 对慢端点执行 EXPLAIN 分析
6. 测试冷启动性能（容器重启后首次请求）
7. 测试 Redis 不可用时的降级行为
