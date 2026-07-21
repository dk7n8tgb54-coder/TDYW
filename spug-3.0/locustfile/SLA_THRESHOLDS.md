# 压测 SLA 阈值定义(上线前必补 🔴)

> 本文档定义所有压测脚本的通过阈值。压测完成后,对照本表判定是否达标。
> 不达标项必须修复或调整配置后重测,否则不可上线。

## 判定等级

| 等级 | 含义 | 处理 |
|---|---|---|
| ✅ 达标 | 全部指标满足阈值 | 可上线 |
| ⚠️ 临界 | P95 超阈值但 <2倍,或失败率 0.1%-1% | 评估后决定,建议优化 |
| ❌ 不达标 | P95 超阈值 2倍,或失败率 >1%,或 OOM/500 | **必须修复** |

---

## 通用阈值(所有接口)

| 指标 | 阈值 | 说明 |
|---|---|---|
| 失败率 | < 0.1% | 不含预期 403/404 |
| HTTP 500 率 | = 0 | 任何 500 视为不达标 |
| 平均响应时间 | < 500ms | 读接口 |
| DB 连接数 | < 240 | max_connections=300,留 20% 余量 |
| tdyw 容器内存 | < 1.8G | limit=2G,留 10% 余量 |
| tdyw-db 容器内存 | < 2.7G | limit=3G |
| kkfileview 容器内存 | < 1.35G | limit=1.5G |

---

## 分场景阈值

### 1. 登录(`account_login_stress.py`)

| 指标 | 阈值 | 说明 |
|---|---|---|
| P95 @ 200 并发 | < 300ms | 登录走 PBKDF2,耗时主要在 hash |
| QPS @ 200 并发 | > 100 | 4 个 gunicorn worker × 16 线程 |
| 失败率 | = 0 | 限流/锁定视为失败 |

### 2. 资料 CRUD(`document_stress.py`)

| 接口 | P95 | 说明 |
|---|---|---|
| 文件夹列表 | < 200ms | 高频读 |
| 文件上传(10KB) | < 500ms | 小文件 |
| 分片上传(3MB) | < 3s | 3 分片顺序传 |
| 合并分片 | < 2s | 接口返回快,实际合并在 Celery |
| 删除文件 | < 300ms | |
| 磁盘使用 | < 200ms | 聚合查询 |

### 3. 高并发锁竞争(`locustfile_document.py`)

| 指标 | 阈值 | 说明 |
|---|---|---|
| 同名合并竞争 P95 | < 5s | 锁等待 |
| 并发分片上传失败率 | < 1% | 锁竞争失败可重试 |

### 4. 文件夹深度(`locustfile_folder_depth.py`)

| 指标 | 阈值 | 说明 |
|---|---|---|
| 深层创建(depth=10) P95 | < 500ms | |
| 文件夹树递归 P95 | < 2s | 取决于节点数 |
| 极限深度(50层) | 应被拒绝 | 系统有深度限制 |

### 5. PDF 导出(`locustfile_pdf_export.py`)🔴 高风险

| 指标 | 阈值 | 说明 |
|---|---|---|
| 值班日志导出 P95 | < 15s | 单次导出 |
| 并发 10 导出 OOM | 不发生 | tdyw 内存 < 1.8G |
| 并发 20 导出 OOM | 不发生 | 极限测试 |

### 6. 大文件下载(`locustfile_download.py`)

| 指标 | 阈值 | 说明 |
|---|---|---|
| 小文件下载 P95 | < 200ms | 10KB |
| 大文件下载 P95 | < 2s | 3MB |
| 下载吞吐量 | > 50 MB/s | 30 并发 |
| Gunicorn worker 占用 | < 16 | 不应全占满 |

### 7. kkFileView 预览(`locustfile_kkfileview_preview.py`)🔴 高风险

| 指标 | 阈值 | 说明 |
|---|---|---|
| 预览令牌 P95 | < 200ms | 轻量 |
| 普通预览 P95 | < 1s | 图片/PDF |
| office 预览 P95 | < 30s | LibreOffice 转换 |
| 并发 15 预览 OOM | 不发生 | kkfileview < 1.35G |

### 8. 审计日志(`locustfile_audit_log.py`)

| 指标 | 阈值 | 说明 |
|---|---|---|
| 首页 P95 | < 300ms | 20 条 |
| 深页(page=200) P95 | < 2s | OFFSET 4000 |
| 时间筛选 P95 | < 1s | 7 天范围 |
| 导出(7天) P95 | < 10s | 全量 |

### 9. 混合负载(`locustfile_mixed_workload.py`)

| 指标 | 阈值 | 说明 |
|---|---|---|
| 整体 QPS @ 50 并发 | > 30 | 读多写少 |
| 整体 P95 | < 1s | 混合负载 |
| 失败率 | < 1% | 含 401 重登录 |
| DB 连接数 | < 240 | 300 上限 |

### 10. 小文件批量上传高峰(`locustfile_bulk_upload.py`)🔴 高风险

| 指标 | 阈值 | 说明 |
|---|---|---|
| 上传 QPS @ 9 并发 | > 30 | 3 账号 × 3 并发文件 |
| 上传 P95 | < 500ms | 10KB 小文件 |
| 失败率 | < 1% | DB 写入/磁盘落盘 |
| Gunicorn worker 占用 | < 64 | 4 worker × 16 线程 |
| 磁盘 I/O | 无堆积 | 小文件落盘不阻塞 |

---

## 监控命令清单(压测时另开终端)

```bash
# 容器资源
docker stats tdyw tdyw-db kkfileview

# MySQL 连接数
docker exec tdyw-db sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SHOW STATUS LIKE \"Threads_connected\";"'

# MySQL 慢查询计数
docker exec tdyw-db sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SHOW GLOBAL STATUS LIKE \"Slow_queries\";"'

# Gunicorn/Celery 日志
docker exec tdyw sh -c 'tail -f /data/spug/spug_api/logs/*.log'

# DB 连接池健康(项目自带)
curl -s http://localhost/api/document/health/db-pool/ | python -m json.tool
```

---

## 压测报告模板

每次压测完成后,填写下表存档:

```
## 压测报告 - YYYY-MM-DD

### 环境
- 容器: tdyw:xxxx / tdyw-db / kkfileview
- 并发: -u XX -r XX -t XXm

### 结果
| 脚本 | QPS | P95 | 失败率 | 判定 |
|---|---|---|---|---|
| account_login_stress | | | | |
| document_stress | | | | |
| locustfile_pdf_export | | | | |
| locustfile_download | | | | |
| locustfile_kkfileview_preview | | | | |
| locustfile_audit_log | | | | |
| locustfile_mixed_workload | | | | |

### 瓶颈分析
(填)

### 不达标项处理
(填)

### 结论
[ ] 可上线  [ ] 需优化后重测  [ ] 阻塞上线
```
