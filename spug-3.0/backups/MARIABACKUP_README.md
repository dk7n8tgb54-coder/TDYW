# MariaDB Backup 定时备份使用说明

## 功能特点

- 使用 **mariabackup** 进行物理热备份（不锁表，不影响业务）
- 自动清理过期备份（默认保留7天）
- 支持备份压缩，节省存储空间
- 完整的日志记录

## 前置要求

### 1. Docker 容器名称
确保 MariaDB 容器名称为 `tdyw-db`，否则修改脚本中的 `CONTAINER_NAME`。

### 2. 检查 mariabackup 是否已安装

```bash
# 在宿主机执行
docker exec tdyw-db which mariabackup
```

如果输出类似 `/usr/bin/mariabackup`，说明已安装。

### 3. 手动安装 mariabackup（如果未安装）

#### Ubuntu/Debian
```bash
docker exec tdyw-db apt-get update
docker exec tdyw-db apt-get install -y mariadb-backup
```

#### CentOS/RHEL
```bash
docker exec tdyw-db yum install -y MariaDB-backup
```

#### Alpine
```bash
docker exec tdyw-db apk add --no-cache mariadb-backup
```

## 使用方法

### 1. 手动执行备份

```bash
# 在宿主机执行
python e:\TDYW\spug-3.0\backups\mariabackup_backup.py
```

### 2. 配置定时备份（Windows 任务计划程序）

#### 创建任务计划

```powershell
# 以管理员身份打开 PowerShell，执行以下命令
# 创建每天凌晨2点执行备份的任务
$action = New-ScheduledTaskAction -Execute "python" -Argument "E:\TDYW\spug-3.0\backups\mariabackup_backup.py"
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Spug-MariaDB-Backup" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Spug数据库定时备份"
```

#### 手动创建任务计划

1. 打开"任务计划程序"（搜索"Task Scheduler"）
2. 点击右侧"创建基本任务"
3. 填写名称：`Spug-MariaDB-Backup`
4. 选择触发器：每天
5. 设置时间：凌晨2:00
6. 选择操作：启动程序
   - 程序：`python`（或完整路径如 `C:\Python39\python.exe`）
   - 参数：`E:\TDYW\spug-3.0\backups\mariabackup_backup.py`
7. 完成创建

### 3. 修改备份配置

编辑 `mariabackup_backup.py` 文件中的配置区域：

```python
# Docker 配置
CONTAINER_NAME = "tdyw-db"  # MariaDB 容器名称

# 备份配置
BACKUP_DIR = r"E:\TDYW\spug-3.0\backups\mariabackup"
RETENTION_DAYS = 7  # 保留最近7天的备份

# MariaDB 连接配置
DB_USER = "root"
DB_PASS = "spug.cc"
DB_NAME = "spug"
```

## 备份恢复

### 1. 解压备份

```powershell
# 解压备份文件到临时目录
Expand-Archive -Path "E:\TDYW\spug-3.0\backups\mariabackup\backup_20260320_020000.zip" -DestinationPath "E:\temp\restore"
```

### 2. 停止容器

```bash
docker stop tdyw-db
```

### 3. 备份当前数据（可选）

```bash
# 防止恢复失败，先备份当前数据
docker cp tdyw-db:/var/lib/mysql E:\temp\current_backup
```

### 4. 清空数据目录

```bash
# 删除容器内的 MySQL 数据目录
docker exec tdyw-db rm -rf /var/lib/mysql/*
```

### 5. 恢复备份

```bash
# 将备份文件复制到容器内
docker cp E:\temp\restore\backup_20260320_020000 tdyw-db:/tmp/restore_backup

# 恢复数据
docker exec tdyw-db mariabackup --copy-back --target-dir=/tmp/restore_backup --user=root --password=spug.cc

# 修复权限
docker exec tdyw-db chown -R mysql:mysql /var/lib/mysql
```

### 6. 启动容器

```bash
docker start tdyw-db
```

### 7. 验证恢复

```bash
# 检查容器日志
docker logs tdyw-db

# 进入容器验证数据
docker exec -it tdyw-db mysql -uroot -pspug.cc -e "SHOW DATABASES;"
```

## 日志查看

备份日志位置：`E:\TDYW\spug-3.0\backups\mariabackup\backup.log`

```powershell
# 查看最近100行日志
Get-Content E:\TDYW\spug-3.0\backups\mariabackup\backup.log -Tail 100
```

## 常见问题

### 1. mariabackup 命令不存在

**解决方法**：手动安装 mariadb-backup（见上文）

### 2. 权限不足

**解决方法**：确保任务计划程序使用 SYSTEM 账户运行

### 3. 容器名称不匹配

**解决方法**：查看容器名称，修改脚本配置
```bash
docker ps --format "{{.Names}}"
```

### 4. 备份失败

查看日志文件获取详细错误信息：
```powershell
type E:\TDYW\spug-3.0\backups\mariabackup\backup.log
```

## 与 mysqldump 对比

| 特性 | mariabackup | mysqldump |
|------|-------------|-----------|
| 备份类型 | 物理备份 | 逻辑备份 |
| 速度 | 快 | 慢 |
| 锁表 | 不锁表（热备份） | 部分锁表 |
| 恢复速度 | 快 | 慢 |
| 备份文件大小 | 大（接近原数据大小） | 小 |
| 跨版本迁移 | 不支持 | 支持 |
| 粒度 | 全量备份 | 可单表备份 |

**推荐使用 mariabackup 进行全量备份**，适合大数据库和生产环境。
