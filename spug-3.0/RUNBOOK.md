# TDYW 标准化应急预案 (Runbook)

> **适用**：spug-3.0 / TDYW 单机 Docker Compose 部署 | **编制**：2026-07-31 | **版本**：v1.0

---

## 0. 基础设施速查

### 容器拓扑

| 容器 | 镜像 | 内存上限 | 职责 |
|------|------|---------|------|
| `tdyw` | tdyw:07272 | 2G | Nginx + Redis + Gunicorn(:9001 普通/:9003 上传) + Daphne(:9002 WS) + 6 Celery worker + Beat |
| `tdyw-db` | mysql:0601 (MariaDB 10.8.2) | 3G | 数据库, buffer_pool 2G, max_connections 300, 仅 127.0.0.1:3306 |
| `tdyw-kkfileview` | keking/kkfileview:4.1.0 | 1.5G | 文件预览, 内部 :8012 |

### 关键路径（容器内）

| 路径 | 说明 |
|------|------|
| `/data/spug/spug_api` | 应用根目录 |
| `/data/spug/spug_api/storage/documents` | 资料库文件 |
| `/data/spug/spug_api/storage/document_chunks` | 上传分片 |
| `/data/spug/spug_api/media` | 附件存储 |
| `/data/spug/spug_api/logs/` | 应用日志 |
| `/var/log/supervisor/` | Supervisor/Nginx 日志 |
| `/var/lib/mysql` | 数据库数据 |

### 健康检查 & 告警

```bash
# 健康检查（Docker healthcheck 也用此端点）
curl -sf https://localhost/api/document/health/   # 200=ok, 503=error

# DB 连接池监控（需认证）
curl -sf -H "Authorization: Bearer <token>" https://localhost/api/document/health/db-pool/

# 运行 DB 监控脚本
bash database_maintenance/db_monitor_alert.sh --warn-only
```

- **告警入口**：`libs/alert.py:send_alert()` -> DB Alert 表 + Redis List + SMTP 邮件
- **告警阈值**：表行数 100W/500W | 表大小 500MB/2GB | 慢查询 50/200 条/h | 磁盘 75%/90% | 连接率 70%/90%

### 通用诊断命令

```bash
# 容器状态一览
wsl bash -c 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'

# Supervisor 进程状态
wsl bash -c 'docker exec tdyw supervisorctl status'

# 应用日志（最近 100 行）
wsl bash -c 'docker exec tdyw tail -100 /data/spug/spug_api/logs/api_err.log'
wsl bash -c 'docker exec tdyw tail -100 /data/spug/spug_api/logs/celery_err.log'

# Nginx 日志
wsl bash -c 'docker exec tdyw tail -100 /var/log/nginx/error.log'

# 数据库进程列表
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW PROCESSLIST\""'
```

---

## 1. 应急响应流程

### 故障分级

| 级别 | 定义 | 响应时间 | 示例 |
|------|------|---------|------|
| P0 | 全站不可用 | 立即 | 502 全站、磁盘满 |
| P1 | 核心功能不可用 | 15 分钟 | 数据库卡死、数据误操作、主库故障 |
| P2 | 部分功能受影响 | 1 小时 | 上线回滚、Celery 堆积、预览不可用 |
| P3 | 非核心降级 | 4 小时 | Redis 不可用、单接口报错 |

### 5 步法

```
接报 -> 诊断 -> 止血 -> 恢复 -> 复盘
```

1. **接报**：记录时间、报告人、现象
2. **诊断**：按本文档对应章节执行诊断步骤
3. **止血**：先恢复服务（重启/降级/切流），再找根因
4. **恢复**：执行完整恢复操作
5. **复盘**：填写故障报告，更新本文档

**原则**：止血优先于根因分析 | 双人确认 P0/P1 操作 | 每步记录时间戳

---

## 2. 数据库卡死 / 死锁 / 连接耗尽 (P1)

### 2.1 诊断

```bash
# 1. 确认 DB 进程存活
wsl bash -c 'docker exec tdyw-db sh -c "mysqladmin ping -h 127.0.0.1 -uroot -p\"\$MYSQL_ROOT_PASSWORD\""'
# 预期: mysqld is alive

# 2. 检查连接数
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW STATUS LIKE '\''Threads_connected'\''; SHOW VARIABLES LIKE '\''max_connections'\''\""'

# 3. 查找长事务（>60s）
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SELECT id, user, host, time, state, LEFT(info, 100) as query FROM information_schema.processlist WHERE command != '\''Sleep'\'' AND time > 60 ORDER BY time DESC\""'

# 4. 查看锁等待
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SELECT * FROM information_schema.INNODB_LOCK_WAITS\""'

# 5. InnoDB 死锁信息
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW ENGINE INNODB STATUS\G\"" 2>&1' | head -100

# 6. 慢查询日志
wsl bash -c 'docker exec tdyw-db tail -50 /var/log/mysql/slow'
```

### 2.2 止血

#### 连接数耗尽

```bash
# KILL 空闲 > 5 分钟的连接
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -N -e \"SELECT CONCAT('\''KILL '\'', id, '\'';'\'') FROM information_schema.processlist WHERE command='\''Sleep'\'' AND time > 300\""'

# 临时调高 max_connections（重启失效，需改 mysqlnew.cnf 持久化）
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SET GLOBAL max_connections = 400\""'

# 重启应用释放连接池
wsl bash -c 'docker restart tdyw'
```

#### 死锁 / 锁等待

```bash
# 找到持锁最久的事务，KILL 它（替换 <PID>）
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SELECT id, time, LEFT(info, 200) FROM information_schema.processlist WHERE state LIKE '\''Waiting%'\'' OR state LIKE '\''lock%''\'' ORDER BY time DESC LIMIT 10\""'

wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"KILL <PID>\""'
```

#### DB 完全无响应

```bash
wsl bash -c 'docker restart tdyw-db'
# 等待 60s 确认存活
wsl bash -c 'docker exec tdyw-db sh -c "mysqladmin ping -h 127.0.0.1 -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --wait=60"'
# 重启应用
wsl bash -c 'docker restart tdyw'
# 验证
curl -sf https://localhost/api/document/health/
```

### 2.3 预防

- cron 每周一 08:00 执行 `db_monitor_alert.sh --warn-only`
- 慢查询 > 50 条/h 需排查
- 连接率持续 > 70% 需检查连接泄漏
- 大批量操作必须非高峰 + `LIMIT` 分批

---

## 3. 数据误操作恢复 (P1)

### 3.1 紧急止血（黄金 5 分钟）

> **立即停止写入，防止覆盖！**

```bash
# 1. 停止应用（DB 保留运行）
wsl bash -c 'docker stop tdyw'

# 2. 立即创建当前数据库快照（事故现场）
wsl bash -c 'docker exec tdyw-db sh -c "mariadb-dump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --single-transaction --all-databases --routines --triggers | gzip > /tmp/db_snapshot_$(date +%Y%m%d_%H%M%S).sql.gz"'

# 3. 验证快照
wsl bash -c 'docker exec tdyw-db sh -c "gzip -t /tmp/db_snapshot_*.sql.gz && echo GZIP_OK"'

# 4. 复制到宿主机归档
wsl bash -c 'docker cp tdyw-db:/tmp/db_snapshot_$(date +%Y%m%d_%H%M%S).sql.gz /data/backups/tdyw/'
```

### 3.2 恢复方案选择

| 误操作 | 推荐方案 | 预计耗时 |
|--------|---------|---------|
| UPDATE 错误条件 | binlog 回放 + 反向 SQL | 30min ~ 2h |
| DELETE 少量行 | binlog 提取 INSERT | 30min ~ 1h |
| DELETE 大量行 / DROP / TRUNCATE | 从备份集恢复到临时库 | 1 ~ 4h |
| 误删文件 | 从备份集 documents.tar.gz 恢复 | 30min ~ 2h |

### 3.3 方案 A：binlog 恢复（少量行误操作）

```bash
# 1. 查看 binlog 列表
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW BINARY LOGS\""'

# 2. 查看 binlog 事件，定位误操作位置
wsl bash -c 'docker exec tdyw-db sh -c "mysqlbinlog --base64-output=DECODE-ROWS -v /var/lib/mysql/mysql-bin.<NNNNNN>" 2>&1' | grep -A5 -B5 "DELETE\|UPDATE" > /tmp/binlog_events.txt

# 3. 提取误操作之前的变更 SQL
wsl bash -c 'docker exec tdyw-db sh -c "mysqlbinlog --start-position=1 --stop-position=<误操作前pos> /var/lib/mysql/mysql-bin.<NNNNNN> > /tmp/replay_before.sql"'

# 4. 在临时库回放
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"CREATE DATABASE IF NOT EXISTS tdyw_recover\""'
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" tdyw_recover < /tmp/replay_before.sql"'

# 5. 从临时库提取需要的数据，导入生产库
wsl bash -c 'docker exec tdyw-db sh -c "mysqldump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" tdyw_recover <table_name> | mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" tdyw"'
```

### 3.4 方案 B：从备份集恢复到临时库（大量行/DROP/TRUNCATE）

```bash
# 1. 定位备份集
ls -lt /data/backups/tdyw/backup_sets/
# 选取: backup_set_YYYYmmdd_HHMMSS/

# 2. 校验完整性
cd /data/backups/tdyw/backup_sets/backup_set_YYYYmmdd_HHMMSS
sha256sum -c SHA256SUMS

# 3. 创建临时库并恢复
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"CREATE DATABASE IF NOT EXISTS tdyw_recover\""'
wsl bash -c 'docker cp /data/backups/tdyw/backup_sets/backup_set_YYYYmmdd_HHMMSS/database.sql.gz tdyw-db:/tmp/'
wsl bash -c 'docker exec tdyw-db sh -c "zcat /tmp/database.sql.gz | mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" tdyw_recover"'

# 4. 从临时库提取需要的表/行，导入生产库
wsl bash -c 'docker exec tdyw-db sh -c "mysqldump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" tdyw_recover <table_name> | mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" tdyw"'

# 5. 恢复后清理临时库
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"DROP DATABASE tdyw_recover\""'
```

### 3.5 方案 C：恢复误删文件

```bash
# 1. 解压 documents 备份到临时目录
mkdir -p /tmp/restore_docs
tar xzf /data/backups/tdyw/backup_sets/backup_set_YYYYmmdd_HHMMSS/documents.tar.gz -C /tmp/restore_docs

# 2. 复制误删文件回生产目录
docker cp /tmp/restore_docs/<relative_path> tdyw:/data/spug/spug_api/storage/documents/<relative_path>

# 3. 清理临时文件
rm -rf /tmp/restore_docs
```

### 3.6 恢复后验证

```bash
wsl bash -c 'docker start tdyw'
sleep 30
curl -sf https://localhost/api/document/health/
# 通过前端/API 验证数据正确性
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 tdyw python /data/spug/spug_api/manage.py check'
```

### 3.7 预防

- 批量操作先 `SELECT` 确认范围再 `DELETE/UPDATE`
- 高风险操作用事务包裹：`BEGIN; ... ; ROLLBACK;` 确认后 `COMMIT`
- 禁止生产库 `TRUNCATE/DROP`，改用逻辑删除
- 生产账号无 `DROP/TRUNCATE` 权限
- 每日全量备份 + binlog 持续，确保 RPO ≤ 24h

---

## 4. 版本上线回滚 (P2)

### 4.1 回滚决策

```
上线后发现问题
├── 仅前端问题 -> 回滚前端构建产物（5min）
├── 仅后端代码 -> 回滚后端镜像（10min）
├── 涉及 migration -> 评估反向 migration（30min+）
└── 涉及数据变更 -> 参见 §3
```

### 4.2 仅前端回滚

```bash
# 从 git 恢复旧版前端并构建
cd /path/to/project/spug_web
git checkout <previous_tag>
npm run build
# 构建产物在 spug_web/build/，Nginx 静态文件即时生效
curl -sf https://localhost/ | head -5
```

### 4.3 后端代码回滚（无 migration）

```bash
# 1. 确认当前镜像
docker inspect --format='{{.Config.Image}}' tdyw

# 2. 确认旧镜像存在
docker images | grep tdyw

# 3. 修改 docker/docker-compose.yml 的 image 行为旧版 tag
#    image: tdyw:<old_tag>

# 4. 重启容器
cd /path/to/project/docker
wsl bash -c 'docker compose -f docker-compose.yml up -d tdyw'

# 5. 等待健康检查
sleep 60
curl -sf https://localhost/api/document/health/

# 6. 确认 Celery worker
wsl bash -c 'docker exec tdyw supervisorctl status'
```

### 4.4 涉及 migration 的回滚

> **必须先备份数据库！**

```bash
# 1. 备份当前数据库
wsl bash -c 'docker exec tdyw-db sh -c "mariadb-dump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --single-transaction tdyw | gzip > /tmp/pre_rollback_$(date +%Y%m%d_%H%M%S).sql.gz"'
wsl bash -c 'docker exec tdyw-db sh -c "gzip -t /tmp/pre_rollback_*.sql.gz && echo GZIP_OK"'

# 2. 确认 migration 状态
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py showmigrations <app_name>'

# 3. 执行反向 migration
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py migrate <app_name> <target_migration>'

# 4. git 回滚代码 + 重新构建镜像
cd /path/to/project
git checkout <previous_tag>
docker build -t tdyw:<rollback_tag> -f docker/Dockerfile .

# 5. 重启容器
wsl bash -c 'docker stop tdyw && docker rm tdyw'
cd docker && wsl bash -c 'docker compose -f docker-compose.yml up -d tdyw'

# 6. 验证
curl -sf https://localhost/api/document/health/
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'
```

### 4.5 预防

- 上线前必须备份（`backup_set_create.sh`）
- 每次上线前用 `tdyw-test` 容器验证 migration
- 保留前一个版本的 Docker 镜像 tag
- 灰度发布：先在 `tdyw-test` 验证再推 `tdyw`
- migration 必须可逆（每个 migration 有 `migrations.ReverseField` 或对应反向操作）

---

## 5. 主库故障切换 (P1)

### 5.1 适用场景

单机 Docker Compose 部署**无主从架构**。此章节覆盖以下场景：

- `tdyw-db` 容器崩溃且无法重启
- MariaDB 数据文件损坏
- 宿主机磁盘故障需迁移

### 5.2 诊断

```bash
# 1. 检查容器状态
wsl bash -c 'docker ps -a --filter name=tdyw-db --format "{{.Status}}"'

# 2. 检查日志
wsl bash -c 'docker logs tdyw-db --tail 100'

# 3. 检查磁盘
wsl bash -c 'df -h /var/lib/docker/volumes'

# 4. 尝试启动
wsl bash -c 'docker start tdyw-db'
sleep 10
wsl bash -c 'docker exec tdyw-db sh -c "mysqladmin ping -h 127.0.0.1 -uroot -p\"\$MYSQL_ROOT_PASSWORD\""'
```

### 5.3 方案 A：容器重建（数据卷完好）

```bash
# 1. 停止应用（停止写入）
wsl bash -c 'docker stop tdyw'

# 2. 删除损坏的 DB 容器（数据卷 tdyw-mysql-data 保留）
wsl bash -c 'docker stop tdyw-db && docker rm tdyw-db'

# 3. 重新创建 DB 容器（复用数据卷）
cd /path/to/project/docker
wsl bash -c 'docker compose -f docker-compose.yml up -d tdyw-db'

# 4. 等待健康检查（约 60 秒）
wsl bash -c 'docker exec tdyw-db sh -c "mysqladmin ping -h 127.0.0.1 -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --wait=60"'

# 5. 重启应用
wsl bash -c 'docker start tdyw'
curl -sf https://localhost/api/document/health/
```

### 5.4 方案 B：从备份集完整恢复（数据卷损坏）

> 使用 `backups/backup_set_restore.sh`，详见 `backups/还原脚本维护手册.md`

```bash
# 1. 停止应用
wsl bash -c 'docker stop tdyw'

# 2. 删除损坏的 DB 容器和数据卷
wsl bash -c 'docker stop tdyw-db && docker rm tdyw-db'
wsl bash -c 'docker volume rm tdyw-mysql-data'

# 3. 重新创建空的 DB 容器
cd /path/to/project/docker
wsl bash -c 'docker compose -f docker-compose.yml up -d tdyw-db'

# 4. 等待 DB 初始化完成
sleep 30
wsl bash -c 'docker exec tdyw-db sh -c "mysqladmin ping -h 127.0.0.1 -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --wait=60"'

# 5. 执行生产逻辑恢复（会覆盖数据库、documents、media）
RESTORE_CLIENT_CNF=/etc/tdyw-backup/tdyw_restore.cnf \
DATABASE_RESTORE_MODE=logical \
./backups/backup_set_restore.sh --mode production backup_set_YYYYmmdd_HHMMSS

# 6. 重启应用
wsl bash -c 'docker start tdyw'
sleep 30
curl -sf https://localhost/api/document/health/

# 7. 验证数据完整性
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 tdyw python /data/spug/spug_api/manage.py check'
```

### 5.5 方案 C：迁移到新宿主机

```bash
# === 在旧宿主机 ===
# 1. 停止所有服务
wsl bash -c 'docker compose -f /path/to/docker/docker-compose.yml down'

# 2. 备份数据卷
wsl bash -c 'docker run --rm -v tdyw-mysql-data:/data -v tdyw-documents:/docs -v tdyw-media:/media -v tdyw-document-chunks:/chunks -v /backup:/backup alpine tar czf /backup/tdyw_volumes_$(date +%Y%m%d).tar.gz /data /docs /media /chunks'

# === 在新宿主机 ===
# 3. 复制项目代码和 docker 目录
# 4. 恢复数据卷
wsl bash -c 'docker volume create tdyw-mysql-data && docker volume create tdyw-documents && docker volume create tdyw-media && docker volume create tdyw-document-chunks'
wsl bash -c 'docker run --rm -v tdyw-mysql-data:/data -v tdyw-documents:/docs -v tdyw-media:/media -v tdyw-document-chunks:/chunks -v /backup:/backup alpine tar xzf /backup/tdyw_volumes_*.tar.gz -C /'

# 5. 配置 .env 文件（数据库密码、密钥等）
cp docker/.env.example docker/.env
# 编辑 .env 填入正确配置

# 6. 启动服务
cd /path/to/docker
wsl bash -c 'docker compose -f docker-compose.yml up -d'

# 7. 验证
sleep 60
curl -sf https://localhost/api/document/health/
```

### 5.6 预防

- 每日全量备份 + binlog，确保 RPO ≤ 24h
- 定期恢复演练（使用 `--mode drill`）：
  ```bash
  ./backups/backup_set_restore.sh --mode drill backup_set_YYYYmmdd_HHMMSS
  ```
- 宿主机磁盘监控：`df -h` 超过 75% 告警
- 考虑未来部署 MariaDB 主从复制提升可用性

---

## 6. 磁盘满应急 (P0)

### 6.1 诊断

```bash
# 1. 查看整体磁盘使用
wsl bash -c 'df -h'

# 2. 查看 Docker 卷占用
wsl bash -c 'docker system df -v'

# 3. 查看各容器日志大小
wsl bash -c 'docker exec tdyw du -sh /var/log/supervisor/ /data/spug/spug_api/logs/ /var/log/nginx/'
wsl bash -c 'docker exec tdyw-db du -sh /var/lib/mysql/ /var/log/mysql/'

# 4. 查看大文件 TOP 20
wsl bash -c 'docker exec tdyw find /data/spug/spug_api -type f -size +100M -exec ls -lh {} \; 2>/dev/null | sort -k5 -rh | head -20'

# 5. 查看数据库表大小
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SELECT table_name, ROUND(data_length/1024/1024,2) as data_mb, ROUND(index_length/1024/1024,2) as index_mb FROM information_schema.tables WHERE table_schema='\''tdyw'\'' ORDER BY data_mb DESC LIMIT 20\""'
```

### 6.2 紧急清理（按优先级）

#### 优先级 1：清理容器日志（安全，无风险）

```bash
# 清理应用日志（保留最近 7 天）
wsl bash -c 'docker exec tdyw find /data/spug/spug_api/logs -name "*.log*" -mtime +7 -delete'
wsl bash -c 'docker exec tdyw find /var/log/supervisor -name "*.log*" -mtime +7 -delete'
wsl bash -c 'docker exec tdyw truncate -s 0 /var/log/nginx/access.log'
wsl bash -c 'docker exec tdyw truncate -s 0 /var/log/nginx/error.log'

# 清理 DB 慢查询日志（保留最近 7 天）
wsl bash -c 'docker exec tdyw-db find /var/log/mysql -name "slow*" -mtime +7 -delete'
```

#### 优先级 2：清理上传分片和孤儿文件（低风险）

```bash
# 查看 document_chunks 目录大小
wsl bash -c 'docker exec tdyw du -sh /data/spug/spug_api/storage/document_chunks'

# 触发 Celery cleanup 任务清理过期分片
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python -c "
from apps.document.tasks.cleanup import cleanup_pending_files
cleanup_pending_files.delay()
print(\"cleanup task dispatched\")
"'

# 清理 is_pending_clean=True 的物理文件
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python -c "
from apps.document.models import FileModel
qs = FileModel.objects.filter(is_pending_clean=True)
print(f\"pending clean: {qs.count()} files\")
"'
```

#### 优先级 3：清理 kkFileView 缓存（安全）

```bash
# kkFileView 缓存
wsl bash -c 'docker exec tdyw-kkfileview du -sh /opt/kkFileView-4.1.0/file'
# 如果 > 1G，清理历史文件
wsl bash -c 'docker exec tdyw-kkfileview find /opt/kkFileView-4.1.0/file -mtime +1 -delete'
```

#### 优先级 4：清理 Docker 无用资源（需确认）

```bash
# 查看可清理空间
wsl bash -c 'docker system df'

# 清理停止的容器 + dangling 镜像 + 无用网络（不会影响运行中的容器）
wsl bash -c 'docker system prune -f'

# 清理未使用的镜像（保留最近 3 个 tag）
wsl bash -c 'docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep tdyw | head -3'
# 确认要保留的镜像后，清理其余
# wsl bash -c 'docker image prune -a --filter "until=168h"'
```

#### 优先级 5：清理数据库 binlog（谨慎）

```bash
# 查看当前 binlog 占用
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW BINARY LOGS\""' | tail -5

# 清理 7 天前的 binlog（保留最近 7 天）
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"PURGE BINARY LOGS BEFORE DATE_SUB(NOW(), INTERVAL 7 DAY)\""'
```

### 6.3 清理后验证

```bash
# 1. 确认磁盘空间已释放
wsl bash -c 'df -h'

# 2. 确认所有容器正常运行
wsl bash -c 'docker ps --format "table {{.Names}}\t{{.Status}}"'

# 3. 健康检查
curl -sf https://localhost/api/document/health/
```

### 6.4 预防

- 设置 cron 每日检查磁盘使用率，超过 75% 发告警
- 日志轮转：已配置 Supervisor `redirect_stderr=true` + logrotate
- kkFileView 缓存定时清理：cron 每日 `find /opt/kkFileView-4.1.0/file -mtime +1 -delete`
- 定期执行 `docker system prune -f`（每周）
- 生产单块机械盘，documents/chunks/media 同处 `/dev/sdd`，合并 worker 并发已降至 1

---

## 7. Celery 任务堆积 / 卡死 (P2)

### 7.1 诊断

```bash
# 1. 查看 Supervisor 中 Celery 进程状态
wsl bash -c 'docker exec tdyw supervisorctl status | grep celery'

# 2. 查看 Celery 日志
wsl bash -c 'docker exec tdyw tail -100 /data/spug/spug_api/logs/celery_err.log'

# 3. 查看 Redis 中任务队列长度
wsl bash -c 'docker exec tdyw redis-cli -n 1 LLEN celery'
# 预期: 小于 100；超过 1000 说明堆积

# 4. 查看各队列长度
wsl bash -c 'docker exec tdyw redis-cli -n 1 KEYS "celery*" | head -20'
wsl bash -c 'docker exec tdyw redis-cli -n 1 LLEN document.merge'
wsl bash -c 'docker exec tdyw redis-cli -n 1 LLEN document.cleanup'
wsl bash -c 'docker exec tdyw redis-cli -n 1 LLEN document.batch'

# 5. 查看 Celery worker 活跃任务
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw celery -A spug_api inspect active --timeout=10 2>/dev/null' || echo "inspect failed"
```

### 7.2 止血

#### 重启卡死的 Celery worker

```bash
# 重启单个 worker（不影响其他）
wsl bash -c 'docker exec tdyw supervisorctl restart spug-celery'
wsl bash -c 'docker exec tdyw supervisorctl restart spug-celery-merge'

# 重启所有 Celery（包括 Beat）
wsl bash -c 'docker exec tdyw supervisorctl restart spug-celery spug-celery-cleanup spug-celery-merge spug-celery-batch spug-celery-thumbnail spug-celery-radio-license spug-celery-beat'
```

#### 清空堆积队列（谨慎！会丢失未执行任务）

```bash
# ⚠️ 仅在确认任务可丢弃时执行
# 清空默认队列
wsl bash -c 'docker exec tdyw redis-cli -n 1 FLUSHDB'
# 注意：这会清空 Redis DB 1 的所有 key（包括 Celery 任务和结果）

# 更精确的方式：只清空指定队列
wsl bash -c 'docker exec tdyw redis-cli -n 1 DEL celery'
wsl bash -c 'docker exec tdyw redis-cli -n 1 DEL document.merge'
```

### 7.3 根因排查

```bash
# 1. 检查是否有死循环任务
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python -c "
from celery.task.control import inspect
i = inspect()
active = i.active()
for worker, tasks in (active or {}).items():
    for t in tasks:
        print(f\"{worker}: {t[\"name\"]} (runtime: {t.get(\"time_start\", \"?\")}s)\")
"'

# 2. 检查 merge worker 是否卡在长合并任务
wsl bash -c 'docker exec tdyw tail -50 /data/spug/spug_api/logs/celery_merge.log'

# 3. 检查 Redis 是否正常
wsl bash -c 'docker exec tdyw redis-cli ping'
# 预期: PONG
```

### 7.4 预防

- merge worker 并发 = 1，缓冲 16MB，fallocate 预分配（已配置）
- 监控队列长度，超过 100 告警
- Celery 任务超时配置：`task_time_limit` / `task_soft_time_limit`
- 长任务考虑拆分为子任务

---

## 8. kkFileView 预览服务不可用 (P2)

### 8.1 诊断

```bash
# 1. 检查容器状态
wsl bash -c 'docker ps --filter name=tdyw-kkfileview --format "{{.Status}}"'

# 2. 检查健康端点
wsl bash -c 'docker exec tdyw curl -sf http://tdyw-kkfileview:8012/ || echo "kkfileview unreachable"'

# 3. 检查日志
wsl bash -c 'docker logs tdyw-kkfileview --tail 50'

# 4. 检查 Nginx 代理配置
wsl bash -c 'docker exec tdyw grep -A5 "kkfileview" /etc/nginx/conf.d/default.conf'
```

### 8.2 止血

```bash
# 重启 kkFileView 容器
wsl bash -c 'docker restart tdyw-kkfileview'

# 等待启动（约 30 秒）
sleep 30
wsl bash -c 'docker exec tdyw curl -sf http://tdyw-kkfileview:8012/ && echo "kkfileview OK"'

# 如果频繁 OOM，考虑清理缓存后重启
wsl bash -c 'docker exec tdyw-kkfileview find /opt/kkFileView-4.1.0/file -mtime +1 -delete'
wsl bash -c 'docker restart tdyw-kkfileview'
```

### 8.3 降级方案

如果 kkFileView 短期无法恢复：

```bash
# 临时关闭预览功能，仅提供下载
# 1. 设置环境变量禁用预览
wsl bash -c 'docker exec tdyw sh -c "echo KKFILEVIEW_DISABLED=true >> /data/spug/spug_api/.env"'

# 2. 重启应用使配置生效
wsl bash -c 'docker restart tdyw'

# 前端会自动降级为仅下载模式
```

### 8.4 预防

- kkFileView 内存限制 1.5G，监控 OOM
- 缓存定时清理：cron 每日 `find /opt/kkFileView-4.1.0/file -mtime +1 -delete`
- kkFileView 回源地址配置为 `http://tdyw`（容器名），需确保 `tdyw` 在 `ALLOWED_HOSTS`

---

## 9. Redis 不可用 (P3)

### 9.1 诊断

```bash
# 1. 检查 Redis 进程
wsl bash -c 'docker exec tdyw supervisorctl status redis'

# 2. 检查连通性
wsl bash -c 'docker exec tdyw redis-cli ping'
# 预期: PONG

# 3. 检查内存使用
wsl bash -c 'docker exec tdyw redis-cli INFO memory | grep used_memory_human'

# 4. 检查日志
wsl bash -c 'docker exec tdyw tail -50 /var/log/supervisor/redis.err.log'
```

### 9.2 止血

```bash
# 重启 Redis
wsl bash -c 'docker exec tdyw supervisorctl restart redis'

# 如果 Redis 进程完全挂掉，重启容器
wsl bash -c 'docker restart tdyw'
```

### 9.3 影响评估

Redis 不可用时的影响：

| 功能 | 影响程度 | 说明 |
|------|---------|------|
| 用户登录 Session | **严重** | 无法登录/维持会话 |
| 权限缓存 `perms_{id}` | **严重** | 每次请求查数据库，性能下降 |
| 磁盘用量缓存 | 轻微 | 直接查文件系统 |
| Celery 任务队列 | **严重** | 任务无法分发执行 |
| 告警通知 | 中等 | 无法写入 Redis List，前端不显示 |
| Dashboard 统计缓存 | 轻微 | 每次查数据库 |

### 9.4 预防

- Redis 配置 `maxmemory-policy allkeys-lru`（已有）
- 监控 Redis 内存使用率
- 考虑 Redis 持久化配置（当前为纯内存，重启丢失）

---

## 10. Nginx 502 / 应用无响应 (P3)

### 10.1 诊断

```bash
# 1. 检查 Nginx 状态
wsl bash -c 'docker exec tdyw supervisorctl status nginx'

# 2. 检查 Nginx 错误日志
wsl bash -c 'docker exec tdyw tail -50 /var/log/nginx/error.log'
# 常见错误: "connect() refused" -> Gunicorn 挂了; "upstream timed out" -> 超时

# 3. 检查 Gunicorn 进程
wsl bash -c 'docker exec tdyw supervisorctl status spug-api spug-api-upload'

# 4. 直接测试 Gunicorn
wsl bash -c 'docker exec tdyw curl -sf http://127.0.0.1:9001/api/document/health/ || echo "gunicorn down"'

# 5. 检查 WebSocket
wsl bash -c 'docker exec tdyw supervisorctl status spug-ws'
```

### 10.2 止血

```bash
# 重启 Gunicorn
wsl bash -c 'docker exec tdyw supervisorctl restart spug-api spug-api-upload'

# 重启 WebSocket
wsl bash -c 'docker exec tdyw supervisorctl restart spug-ws'

# 如果 Gunicorn 无法启动，重启整个容器
wsl bash -c 'docker restart tdyw'
```

### 10.3 Nginx 配置检查

```bash
# 测试 Nginx 配置语法
wsl bash -c 'docker exec tdyw nginx -t'

# 重新加载配置（不停机）
wsl bash -c 'docker exec tdyw nginx -s reload'
```

---

## 附录 A：常用诊断命令速查

### 容器管理

```bash
# 所有容器状态
wsl bash -c 'docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'

# 容器资源使用
wsl bash -c 'docker stats --no-stream'

# 进入容器
wsl bash -c 'docker exec -it tdyw bash'
wsl bash -c 'docker exec -it tdyw-db bash'
```

### 数据库

```bash
# 连接数据库
wsl bash -c 'docker exec -it tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" tdyw"'

# 查看数据库大小
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SELECT table_schema, ROUND(SUM(data_length+index_length)/1024/1024,2) as mb FROM information_schema.tables GROUP BY table_schema\""'

# 查看 InnoDB 状态
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW ENGINE INNODB STATUS\G\"" 2>&1'

# 查看慢查询
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW VARIABLES LIKE '\''slow_query%'\''; SHOW VARIABLES LIKE '\''long_query_time'\''\""'
```

### Redis

```bash
# 连接 Redis
wsl bash -c 'docker exec -it tdyw redis-cli'

# 查看内存
wsl bash -c 'docker exec tdyw redis-cli INFO memory | grep used_memory_human'

# 查看键数量
wsl bash -c 'docker exec tdyw redis-cli DBSIZE'
```

### 应用

```bash
# Django 管理命令
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py showmigrations'
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py dbshell'

# Celery 管理
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw celery -A spug_api inspect active'
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw celery -A spug_api inspect reserved'
```

### 备份

```bash
# 创建备份集
./backups/backup_set_create.sh

# 恢复备份集（演练模式）
RESTORE_CLIENT_CNF=/etc/tdyw-backup/tdyw_restore.cnf \
./backups/backup_set_restore.sh --mode drill backup_set_YYYYmmdd_HHMMSS

# 恢复备份集（生产模式）
RESTORE_CLIENT_CNF=/etc/tdyw-backup/tdyw_restore.cnf \
DATABASE_RESTORE_MODE=logical \
./backups/backup_set_restore.sh --mode production backup_set_YYYYmmdd_HHMMSS
```

---

## 附录 B：联系人 / 通讯录

> 请根据实际情况填写

| 角色 | 姓名 | 手机 | 通讯工具 | 职责 |
|------|------|------|---------|------|
| 运维负责人 | ______ | ______ | ______ | P0/P1 决策、容器/DB 操作 |
| 后端开发 | ______ | ______ | ______ | 代码回滚、migration 操作 |
| 前端开发 | ______ | ______ | ______ | 前端回滚 |
| DBA | ______ | ______ | ______ | 数据库恢复、binlog 操作 |
| 网络管理员 | ______ | ______ | ______ | 网络/防火墙问题 |
| 业务负责人 | ______ | ______ | ______ | 通知用户、业务影响评估 |

### 外部支持

| 服务 | 联系方式 | 说明 |
|------|---------|------|
| 服务器供应商 | ______ | 硬件故障 |
| MariaDB 支持 | https://mariadb.org/support/ | 数据库问题 |
| Docker 支持 | https://docs.docker.com/ | Docker 问题 |

---

## 附录 C：故障复盘模板

```markdown
# 故障复盘报告

## 1. 故障概述
- **故障编号**：INC-YYYYMMDD-NNN
- **级别**：P0/P1/P2/P3
- **发生时间**：YYYY-MM-DD HH:MM
- **恢复时间**：YYYY-MM-DD HH:MM
- **持续时长**：XX 分钟
- **报告人**：______
- **值班人**：______

## 2. 影响范围
- **受影响用户**：______
- **受影响功能**：______
- **数据影响**：无 / 有（描述）

## 3. 时间线
| 时间 | 事件 | 操作人 |
|------|------|--------|
| HH:MM | 告警触发/用户报告 | |
| HH:MM | 开始诊断 | |
| HH:MM | 定位根因 | |
| HH:MM | 执行止血 | |
| HH:MM | 服务恢复 | |
| HH:MM | 完成恢复 | |

## 4. 根因分析
（技术层面的详细分析）

## 5. 止血措施评估
- 止血是否及时？
- 止血操作是否正确？
- 是否需要改进 Runbook？

## 6. 改进项
| 编号 | 改进措施 | 负责人 | 截止日期 | 状态 |
|------|---------|--------|---------|------|
| 1 | | | | |
| 2 | | | | |

## 7. Runbook 更新
- 是否需要更新本文档？
- 是否需要新增章节？
```

---

## 附录 D：变更记录

| 日期 | 版本 | 变更人 | 变更内容 |
|------|------|--------|---------|
| 2026-07-31 | v1.0 | ______ | 初版：覆盖 10 类故障场景 |