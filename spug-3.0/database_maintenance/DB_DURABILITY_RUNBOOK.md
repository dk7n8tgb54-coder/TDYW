# 数据库强刷盘与 binlog 配置变更 Runbook

> 适用：spug-3.0 / TDYW
> 变更对象：`docker/config/mysqlnew.cnf`（生产实际通过 `mysql-entrypoint.sh` 复制到 `/etc/mysql/conf.d/custom.cnf` 生效）
> 编制日期：2026-07-23
> 阶段：Phase 1 强刷盘（不部署 Replica）

## 0. 变更目标

将数据库持久性参数调整为断电零丢失配置：

| 参数 | 变更前 | 变更后 | 说明 |
|---|---|---|---|
| `innodb_flush_log_at_trx_commit` | 2 | **1** | 每次提交刷盘，断电不丢已提交事务 |
| `sync_binlog` | (未设置) | **1** | 每次提交同步 binlog 到磁盘 |
| `innodb_doublewrite` | (默认 ON，未显式) | **ON** | 显式写入，防镜像默认值漂移 |
| `log_bin` | mysql-bin（已开） | mysql-bin | 不变 |
| `binlog_format` | ROW（已开） | ROW | 不变 |
| `binlog_expire_logs_seconds` | 604800（已开） | 604800 | 不变 |

影响范围：仅持久性参数。不触及 `innodb_buffer_pool_size`、`max_connections`、`innodb_log_file_size` 等性能参数。

## 1. 修改前备份要求（必须先完成，未完成不得开始变更）

### 1.1 完整逻辑备份并校验
```bash
# 宿主机（WSL）执行，密码通过容器内环境变量读取，不写入命令历史
wsl bash -c 'docker exec tdyw-db sh -c "mariadb-dump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --single-transaction --all-databases --routines --triggers | gzip > /tmp/db_backup_$(date +%Y%m%d_%H%M%S).sql.gz"'
# 校验完整性
wsl bash -c 'docker exec tdyw-db sh -c "gzip -t /tmp/db_backup_*.sql.gz && echo GZIP_OK"'
# 复制到宿主机归档（避免容器内丢失）
wsl bash -c 'docker cp tdyw-db:/tmp/db_backup_$(docker exec tdyw-db ls -t /tmp/db_backup_*.sql.gz | head -1 | xargs basename) /data/backups/tdyw/'
```

### 1.2 采集修改前基线并归档
```bash
wsl bash -c "docker exec -i tdyw python - < database_maintenance/collect_db_baseline.py" \
  > /data/backups/tdyw/db_baseline_before_$(date +%Y%m%d_%H%M%S).txt
```

### 1.3 记录修改前镜像 digest
```bash
docker inspect --format='{{.Image}}' tdyw-db
docker inspect --format='{{json .RepoDigests}}' tdyw-db
```

### 1.4 保留配置回滚副本
```bash
cp docker/config/mysqlnew.cnf docker/config/mysqlnew.cnf.bak.$(date +%Y%m%d)
```

## 2. 上线步骤（维护窗口，约 5～15 分钟停机）

前置条件：第 1 节全部完成且备份 `gzip -t` 校验通过。

1. **通知用户**进入维护窗口（建议业务低峰，如夜间）。
2. **确认配置文件已修改**（本次已在仓库内修改 `mysqlnew.cnf`）：
   ```bash
   grep -E 'innodb_flush_log_at_trx_commit|sync_binlog|innodb_doublewrite' docker/config/mysqlnew.cnf
   ```
   预期输出：
   ```
   innodb_flush_log_at_trx_commit=1
   sync_binlog=1
   innodb_doublewrite=ON
   ```
3. **重启数据库容器**使配置生效（仅重启 tdyw-db，应用暂不重启）：
   ```bash
   wsl bash -c 'docker restart tdyw-db'
   ```
4. **等待数据库健康**：
   ```bash
   wsl bash -c 'docker exec tdyw-db sh -c "mysqladmin ping -h 127.0.0.1 -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --wait=60"'
   ```
   或观察 `docker ps` 中 tdyw-db 状态变为 `healthy`。
5. **重启应用容器**（确保连接池重建，避免使用旧连接）：
   ```bash
   wsl bash -c 'docker restart tdyw'
   ```
6. **运行发布前审计**，确认无 FAIL：
   ```bash
   wsl bash -c "docker exec -i tdyw python - < scripts/pre_release/audit_config.py"
   ```
   预期：持久性 5 项全部 PASS、业务表引擎 PASS、退出码 0。
7. **采集修改后基线**并归档对比：
   ```bash
   wsl bash -c "docker exec -i tdyw python - < database_maintenance/collect_db_baseline.py" \
     > /data/backups/tdyw/db_baseline_after_$(date +%Y%m%d_%H%M%S).txt
   diff <(cat /data/backups/tdyw/db_baseline_before_*.txt | tail -n +3) \
        <(cat /data/backups/tdyw/db_baseline_after_*.txt | tail -n +3)
   ```

## 3. 运行态验证命令（上线后必须执行）

### 3.1 直接 SQL 验证持久性参数（必须全部符合）
```bash
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"
SHOW VARIABLES WHERE Variable_name IN (
  '\''innodb_flush_log_at_trx_commit'\'',
  '\''sync_binlog'\'',
  '\''log_bin'\'',
  '\''binlog_format'\'',
  '\''innodb_doublewrite'\'',
  '\''binlog_expire_logs_seconds'\''
);\""'
```
预期值：

| Variable_name | Value |
|---|---|
| innodb_flush_log_at_trx_commit | 1 |
| sync_binlog | 1 |
| log_bin | ON |
| binlog_format | ROW |
| innodb_doublewrite | ON |
| binlog_expire_logs_seconds | 604800 |

### 3.2 binlog 已生成
```bash
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"SHOW BINARY LOGS;\""'
```
预期：存在 `mysql-bin.000001` 等文件。

### 3.3 表引擎全 InnoDB
```bash
wsl bash -c 'docker exec tdyw-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"
SELECT ENGINE, COUNT(*) FROM information_schema.TABLES
WHERE TABLE_SCHEMA=database() AND TABLE_TYPE='\''BASE TABLE'\'' GROUP BY ENGINE;\""'
```
预期：仅 `InnoDB` 一行。

### 3.4 业务冒烟
人工或脚本验证：登录、列表查询、上传一条数据、软删除。写接口 P95 不超过变更前 2 倍，无 500。

### 3.5 发布审计脚本
```bash
wsl bash -c "docker exec -i tdyw python - < scripts/pre_release/audit_config.py"
```
退出码必须为 0。

## 4. 回滚说明

### 4.1 回滚条件
仅当强刷盘导致磁盘 I/O 无法满足、出现持续业务故障（写接口大面积超时/500）时，才允许临时回滚。不得因"性能略有下降"就回滚——当前日写入量极低（约 200 条/天），强刷盘影响可忽略。

### 4.2 回滚步骤
1. 恢复配置备份：
   ```bash
   cp docker/config/mysqlnew.cnf.bak.<日期> docker/config/mysqlnew.cnf
   ```
   或手动将 `innodb_flush_log_at_trx_commit` 改回 `2`、注释掉 `sync_binlog` 与 `innodb_doublewrite`。
2. 重启数据库：
   ```bash
   wsl bash -c 'docker restart tdyw-db'
   ```
3. 重新运行第 3 节验证，确认回滚生效。
4. **回滚必须登记**：记录回滚原因、时间、负责人、限定结束时间（建议 ≤7 天）。
5. 优先排查存储瓶颈（更换 SSD / 调整 I/O 调度 / 检查磁盘写屏障），而非长期接受数据丢失窗口。长期保持 `flush=2` 属于未达标状态，`audit_config.py` 会持续 FAIL 阻断后续发布。

## 5. 注意事项

- 本阶段不部署 Replica，`gtid_strict_mode`/`log_slave_updates`/`server_id` 复制相关参数留待 Phase 4，本 Runbook 不强制。
- `sync_binlog=1` + `innodb_flush_log_at_trx_commit=1` 在低写入量下对性能影响极小；不应为微小吞吐提升保留数据丢失窗口。
- **强刷盘参数仅在数据库重启后生效**；修改配置文件不会影响运行中的实例。在重启前不得宣称参数已生效。
- 不得在生产库执行 `RESET MASTER` / `RESET SLAVE` / 手动删除 binlog 等不可逆操作。
- 本变更不删除、不重建任何 Docker volume，不修改表结构。
