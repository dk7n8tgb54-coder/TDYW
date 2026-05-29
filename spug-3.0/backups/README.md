# Spug 备份脚本使用指南

## 目录结构

```
backups/
├── dev/                    # 开发环境
│   ├── manual_backup.sh     # Linux手动备份脚本
│   ├── auto_backup.sh      # Linux自动备份脚本
│   ├── manual_backup.ps1   # Windows手动备份脚本
│   ├── auto_backup.ps1    # Windows自动备份脚本
│   ├── restore.sh         # Linux恢复脚本
│   ├── restore.ps1        # Windows恢复脚本
│   └── setup_scheduled_backup.ps1  # Windows计划任务设置
├── prod/                  # 生产环境（Linux）
│   ├── manual_backup.sh     # 手动备份脚本
│   └── auto_backup.sh      # 自动备份脚本
└── README.md              # 使用文档
```

## 环境说明

- **开发环境**：Windows系统，支持PowerShell脚本
- **生产环境**：Linux系统，使用Bash脚本

## 功能特性

- ✅ 自动加密备份文件（OpenSSL）
- ✅ 自动压缩备份
- ✅ 自动清理旧备份
- ✅ 详细的日志记录
- ✅ 环境分离（开发/生产）
- ✅ 跨平台支持（Windows/Linux）
- ✅ 支持手动和自动备份
- ✅ 一键恢复功能

## 开发环境（Windows）

### 环境准备

1. **安装OpenSSL（用于加密）：**
   - 下载地址：https://slproweb.com/products/Win32OpenSSL.html
   - 安装后重启终端

2. **安装7-Zip（可选，用于更快的压缩）：**
   - 下载地址：https://www.7-zip.org/

### 手动备份

```powershell
cd backups\dev
.\manual_backup.ps1
```

**输出文件：** `spug_dev_backup_YYYYMMDD_HHMMSS.sql.gz.enc`

### 自动备份（每日）

#### 方式一：使用设置脚本（推荐）

```powershell
cd backups\dev
.\setup_scheduled_backup.ps1
```

按照提示：
1. 设置加密密码
2. 确认环境检查通过
3. 确认创建计划任务

**注意：** 需要管理员权限运行

#### 方式二：手动设置

1. **设置环境变量：**
```powershell
[Environment]::SetEnvironmentVariable("BACKUP_ENCRYPT_PASSWORD", "your_secure_password", "User")
```

2. **打开任务计划程序：**
   - Win + R → `taskschd.msc`

3. **创建基本任务：**
   - 名称：`Spug开发环境数据库自动备份`
   - 触发器：每天 02:00
   - 操作：启动程序
   - 程序：`PowerShell.exe`
   - 参数：`-NoProfile -ExecutionPolicy Bypass -File "E:\TDYW\spug-3.0\backups\dev\auto_backup.ps1"`

#### 测试自动备份

```powershell
cd backups\dev
.\auto_backup.ps1
```

**输出文件：** `spug_dev_auto_YYYYMMDD.sql.gz.enc`

### 备份恢复

```powershell
cd backups\dev
.\restore.ps1 spug_dev_backup_20240101_120000.sql.gz.enc
```

### 管理计划任务

```powershell
# 查看任务状态
Get-ScheduledTask -TaskName "Spug开发环境数据库自动备份"

# 手动执行任务
Start-ScheduledTask -TaskName "Spug开发环境数据库自动备份"

# 禁用任务
Disable-ScheduledTask -TaskName "Spug开发环境数据库自动备份"

# 启用任务
Enable-ScheduledTask -TaskName "Spug开发环境数据库自动备份"

# 删除任务
Unregister-ScheduledTask -TaskName "Spug开发环境数据库自动备份" -Confirm:$false
```

## 开发环境（Linux）

## 生产环境

### 手动备份

1. **设置环境变量：**
```bash
export MYSQL_PASSWORD="your_mysql_password"
export BACKUP_ENCRYPT_PASSWORD="your_secure_password"
```

2. **执行备份：**
```bash
cd backups
./prod/manual_backup.sh
```

**输出文件：** `spug_prod_backup_YYYYMMDD_HHMMSS.sql.gz.enc`

### 自动备份（每日）

1. **配置环境变量：**
```bash
# 编辑 ~/.bashrc 或 ~/.bash_profile
export MYSQL_PASSWORD="your_mysql_password"
export BACKUP_ENCRYPT_PASSWORD="your_secure_password"
```

2. **添加到crontab：**
```bash
crontab -e
# 每天凌晨2点执行
0 2 * * * cd /path/to/backups && ./prod/auto_backup.sh
```

3. **测试自动备份：**
```bash
cd backups
./prod/auto_backup.sh
```

**输出文件：** `spug_prod_auto_YYYYMMDD.sql.gz.enc`

## 备份恢复

### 基本用法

```bash
cd backups
./restore.sh <backup_file>
```

### 示例

```bash
# 恢复开发环境备份
./restore.sh spug_dev_backup_20240101_120000.sql.gz.enc

# 恢复生产环境备份
./restore.sh spug_prod_backup_20240101.sql.gz.enc
```

### 环境变量

```bash
export BACKUP_ENCRYPT_PASSWORD="your_password"
```

## 加密配置

### OpenSSL加密（默认）

**加密：**
```bash
openssl enc -aes-256-cbc -salt -in backup.sql -out backup.sql.enc -k "password"
```

**解密：**
```bash
openssl enc -aes-256-cbc -d -in backup.sql.enc -out backup.sql -k "password"
```

### GPG加密

1. **生成密钥对：**
```bash
gpg --gen-key
```

2. **配置脚本：**
```bash
export GPG_RECIPIENT="your_email@example.com"
```

3. **修改加密方法：**
在备份脚本中设置：
```bash
ENCRYPT_METHOD="gpg"
```

**加密：**
```bash
gpg --encrypt --recipient your_email@example.com backup.sql
```

**解密：**
```bash
gpg --decrypt backup.sql.gpg > backup.sql
```

## 手动恢复（不使用脚本）

### 解密并恢复

```bash
# 解密
openssl enc -aes-256-cbc -d -in backup.sql.gz.enc -k "password" | gunzip > backup.sql

# 恢复到开发环境
docker exec -i spug-db mysql -u spug -p spug.cc spug < backup.sql

# 恢复到生产环境
docker exec -i spug-db-prod mysql -u spug -p your_password spug < backup.sql
```

### 一行命令恢复

```bash
# 开发环境
openssl enc -aes-256-cbc -d -in backup.sql.gz.enc -k "password" | gunzip | docker exec -i spug-db mysql -u spug -p spug.cc spug

# 生产环境
openssl enc -aes-256-cbc -d -in backup.sql.gz.enc -k "password" | gunzip | docker exec -i spug-db-prod mysql -u spug -p your_password spug
```

## 备份文件管理

### 查看备份文件

```bash
cd backups
ls -lh
```

### 清理旧备份

手动删除：
```bash
# 删除7天前的备份
find . -name "spug_*.sql.gz*" -mtime +7 -delete
```

自动清理：
脚本会根据 `RETENTION_DAYS` 配置自动清理旧备份：
- 开发环境：默认保留7天
- 生产环境：默认保留30天

### 备份文件命名规则

```
开发环境手动: spug_dev_backup_YYYYMMDD_HHMMSS.sql.gz.enc
开发环境自动: spug_dev_auto_YYYYMMDD.sql.gz.enc
生产环境手动: spug_prod_backup_YYYYMMDD_HHMMSS.sql.gz.enc
生产环境自动: spug_prod_auto_YYYYMMDD.sql.gz.enc
```

## 故障排查

### 备份失败

1. **检查容器状态：**
```bash
docker ps | grep spug-db
```

2. **检查磁盘空间：**
```bash
df -h
```

3. **查看备份日志：**
```bash
cat backups/auto_backup.log
```

### 解密失败

1. **检查密码：**
```bash
echo $BACKUP_ENCRYPT_PASSWORD
```

2. **测试解密：**
```bash
openssl enc -aes-256-cbc -d -in backup.sql.gz.enc -k "password" | head
```

### 恢复失败

1. **检查容器运行状态**
2. **确认数据库连接**
3. **验证备份文件完整性**

## 安全建议

1. **定期测试恢复：** 每月至少测试一次备份恢复
2. **异地备份：** 将备份文件同步到其他服务器或云存储
3. **密码管理：** 使用环境变量或密钥管理工具存储密码
4. **访问控制：** 备份文件目录权限设置为仅管理员可访问
5. **监控告警：** 配置备份失败告警（钉钉、邮件等）

## 生产环境额外建议

1. **异地备份：** 启用远程备份功能
2. **保留策略：** 根据业务需求调整保留天数
3. **备份验证：** 定期验证备份文件完整性
4. **文档化：** 记录备份恢复流程
