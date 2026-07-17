# Docker部署详细步骤指南

## 前置要求

### 1. 服务器环境检查

```bash
# 检查操作系统
cat /etc/os-release

# 检查Docker版本
docker --version
# 要求：Docker 20.10+

# 检查Docker Compose版本
docker-compose --version
# 要求：Docker Compose 1.29+

# 检查内存和磁盘
free -h
df -h
# 建议：内存4GB+，磁盘50GB+
```

### 2. 安装Docker（如未安装）

**CentOS 7/8：**
```bash
# 卸载旧版本
sudo yum remove docker docker-client docker-client-latest docker-common \
  docker-latest docker-latest-logrotate docker-logrotate docker-engine

# 安装必要依赖
sudo yum install -y yum-utils device-mapper-persistent-data lvm2

# 添加Docker仓库
sudo yum-config-manager --add-repo \
  https://download.docker.com/linux/centos/docker-ce.repo

# 安装Docker
sudo yum install -y docker-ce docker-ce-cli containerd.io

# 启动Docker
sudo systemctl start docker
sudo systemctl enable docker

# 安装Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 验证安装
docker --version
docker-compose --version
```

**Ubuntu 18.04/20.04：**
```bash
# 更新包索引
sudo apt-get update

# 安装依赖
sudo apt-get install -y \
  apt-transport-https \
  ca-certificates \
  curl \
  gnupg \
  lsb-release

# 添加Docker GPG密钥
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# 添加Docker仓库
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动Docker
sudo systemctl start docker
sudo systemctl enable docker

# 验证安装
docker --version
docker-compose --version
```

## 部署步骤

### 步骤1：准备部署目录

```bash
# 创建部署目录
sudo mkdir -p /opt/spug
cd /opt/spug

# 创建必要的数据目录
mkdir -p data/mysql
mkdir -p data/repos
mkdir -p data/backend/documents
mkdir -p backups
mkdir -p scripts

# 设置目录权限
sudo chown -R $USER:$USER /opt/spug
```

### 步骤2：上传部署包

**方式A：从Windows上传**
```bash
# 在Windows PowerShell中执行（需要安装WinSCP或类似工具）
# 或使用scp命令
scp -r E:\TDYW\spug-3.0\backups user@server:/opt/spug/scripts/
scp -r E:\TDYW\spug-3.0\data user@server:/opt/spug/
scp E:\TDYW\spug-3.0\docker-compose.yml user@server:/opt/spug/
```

**方式B：打包后上传（推荐）**
```bash
# 在Windows上使用7-Zip或WinRAR压缩为tar.gz格式
# 然后上传
scp spug-deploy.tar.gz user@server:/opt/spug/

# 在服务器上解压
cd /opt/spug
tar -xzf spug-deploy.tar.gz
```

### 步骤3：配置后端settings.py

```bash
# 编辑配置文件
vi data/backend/spug/settings.py

# 找到第66行，修改ALLOWED_HOSTS
# 修改前：
ALLOWED_HOSTS = ['127.0.0.1']

# 修改后（替换为你的服务器IP或域名）：
ALLOWED_HOSTS = ['*', '192.168.1.100', 'yourdomain.com']

# 或简单允许所有IP（不推荐生产环境）：
ALLOWED_HOSTS = ['*']
```

### 步骤4：修改docker-compose.yml

```bash
# 编辑docker-compose.yml
vi docker-compose.yml

# 检查以下配置：

# 1. 数据库密码（生产环境务必修改）
environment:
  - MYSQL_PASSWORD=spug.cc  # 改为强密码
  - MYSQL_ROOT_PASSWORD=spug.cc

# 2. 端口映射（如80端口被占用）
ports:
  - "80:80"  # 可改为 "8080:80"

# 3. 数据卷路径（确保路径正确）
volumes:
  - ./data/mysql:/var/lib/mysql
  - ./data/frontend:/data/spug/spug_web/build
  - ./data/repos:/data/repos
  - ./data/backend:/data/spug/spug_api

# 4. 备份目录（如果需要在容器内执行备份）
#  - ./backups:/var/backups/spug
```

### 步骤5：处理脚本文件

```bash
# 转换脚本换行符（从Windows复制的.sh文件）
cd scripts
sed -i 's/\r$//' backup_db.sh
sed -i 's/\r$//' remote_backup.sh

# 添加执行权限
chmod +x backup_db.sh
chmod +x remote_backup.sh

# 测试脚本是否可执行
./backup_db.sh --help
```

### 步骤6：启动Docker容器

```bash
# 进入部署目录
cd /opt/spug

# 拉取Docker镜像（首次运行需要时间）
docker-compose pull

# 启动所有服务
docker-compose up -d

# 查看容器状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

### 步骤7：验证部署

```bash
# 检查容器是否运行
docker ps
# 应该看到两个容器：spug-db 和 spug

# 检查数据库容器
docker exec -it spug-db mysql -uspug -p
# 输入密码后，应该能登录MySQL

# 退出MySQL
exit

# 检查后端容器
docker exec -it spug ls -la /data/spug/spug_api
# 应该看到后端代码文件
```

### 步骤8：访问测试

```bash
# 获取服务器IP地址
ip addr show | grep inet

# 在浏览器访问
# http://服务器IP

# 首次访问：
# 1. 会显示登录页面
# 2. 使用管理员账号登录
# 默认账号：admin
# 默认密码：spug
```

## 配置防火墙

```bash
# CentOS 7 (firewall)
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-port=3306/tcp  # 如果需要远程访问数据库
sudo firewall-cmd --reload

# Ubuntu (ufw)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 3306/tcp  # 如果需要远程访问数据库
sudo ufw reload

# 检查防火墙状态
sudo firewall-cmd --list-all  # CentOS
sudo ufw status              # Ubuntu
```

## 配置定时备份

### 1. 在宿主机执行备份（推荐）

```bash
# 编辑crontab
crontab -e

# 添加以下内容：
# 每天凌晨2点执行本地备份
0 2 * * * cd /opt/spug/scripts && ./backup_db.sh >> /var/log/spug_backup.log 2>&1

# 每天凌晨3点执行异地备份
0 3 * * * cd /opt/spug/scripts && ./remote_backup.sh >> /var/log/spug_remote_backup.log 2>&1

# 保存并退出（vi编辑器：按ESC，输入:wq回车）
```

### 2. 在Docker容器内执行备份（可选）

```bash
# 方法：在docker-compose.yml中添加备份脚本挂载
volumes:
  - ./backups:/var/backups/spug
  - ./scripts:/opt/scripts

# 设置容器内crontab
docker exec -it spug bash
crontab -e
0 2 * * * /opt/scripts/backup_db.sh
```

## 常用管理命令

### 容器管理

```bash
# 查看运行中的容器
docker-compose ps

# 查看容器日志
docker-compose logs -f              # 实时查看所有日志
docker-compose logs -f db           # 查看数据库日志
docker-compose logs -f spug        # 查看应用日志

# 重启服务
docker-compose restart               # 重启所有服务
docker-compose restart db          # 重启数据库
docker-compose restart spug        # 重启应用

# 停止服务
docker-compose stop

# 启动服务
docker-compose start

# 停止并删除容器
docker-compose down

# 停止并删除容器和数据卷
docker-compose down -v
```

### 数据库管理

```bash
# 进入数据库
docker exec -it spug-db mysql -uspug -p

# 执行SQL脚本
docker exec -i spug-db mysql -uspug -p < init.sql

# 备份数据库（在容器内）
docker exec spug-db mysqldump -uspug -p spug > backup.sql

# 恢复数据库
docker exec -i spug-db mysql -uspug -p spug < backup.sql
```

### 查看资源占用

```bash
# 查看容器资源使用情况
docker stats

# 查看磁盘占用
du -sh /opt/spug/data/*

# 查看日志文件大小
du -sh /var/log/*
```

## 故障排查

### 问题1：容器无法启动

```bash
# 查看详细错误信息
docker-compose logs db
docker-compose logs spug

# 常见原因：
# 1. 端口被占用 - 修改docker-compose.yml中的端口映射
# 2. 数据卷路径错误 - 检查volumes配置
# 3. 权限问题 - 检查文件权限
```

### 问题2：数据库连接失败

```bash
# 检查数据库容器是否运行
docker ps | grep spug-db

# 测试数据库连接
docker exec -it spug-db mysql -hlocalhost -uspug -p

# 检查网络连接
docker network ls
docker network inspect spug_default
```

### 问题3：前端无法访问后端

```bash
# 检查ALLOWED_HOSTS配置
docker exec -it spug cat /data/spug/spug_api/spug/settings.py | grep ALLOWED_HOSTS

# 检查防火墙
sudo firewall-cmd --list-all
sudo ufw status

# 检查容器端口映射
docker port spug
```

### 问题4：文件上传失败

```bash
# 检查documents目录权限
ls -la /opt/spug/data/backend/documents/

# 修复权限
sudo chown -R 1000:1000 /opt/spug/data/backend/documents/

# 检查磁盘空间
df -h /opt/spug
```

## 升级部署

```bash
# 1. 备份当前数据
docker exec spug-db mysqldump -uspug -p spug > backup_before_upgrade.sql

# 2. 停止容器
docker-compose down

# 3. 备份旧版本
cp -r data data_backup_$(date +%Y%m%d)
cp docker-compose.yml docker-compose.yml.backup

# 4. 上传新版本文件
# 替换 data/backend 和 data/frontend

# 5. 启动新版本
docker-compose up -d

# 6. 验证升级
docker-compose logs -f
```

## 安全建议

1. **修改默认密码**
   - MySQL root密码
   - MySQL用户密码
   - 管理员登录密码

2. **限制ALLOWED_HOSTS**
   - 不要使用 `['*']` 在生产环境
   - 明确指定服务器IP或域名

3. **启用HTTPS（可选）**
   - 配置SSL证书
   - 使用Nginx反向代理

4. **定期更新**
   - 更新Docker镜像
   - 更新系统和依赖

5. **监控和日志**
   - 配置日志轮转
   - 监控容器状态
   - 定期检查备份

## 完整部署示例

```bash
#!/bin/bash
# 一键部署脚本

echo "=== 通导运维平台 Docker 部署脚本 ==="

# 1. 创建目录
mkdir -p /opt/spug/{data/{mysql,repos,backend/documents},backups,scripts}

# 2. 上传文件（需要手动执行）
echo "请上传以下文件到 /opt/spug："
echo "  - docker-compose.yml"
echo "  - data/backend/"
echo "  - data/frontend/"
echo "  - scripts/"

# 3. 处理脚本
cd /opt/spug/scripts
sed -i 's/\r$//' *.sh
chmod +x *.sh

# 4. 配置
echo "请编辑 /opt/spug/data/backend/spug/settings.py 修改 ALLOWED_HOSTS"

# 5. 启动
cd /opt/spug
docker-compose pull
docker-compose up -d

# 6. 检查
echo "等待容器启动..."
sleep 10
docker-compose ps

echo "=== 部署完成，请访问 http://服务器IP ==="
```

保存此脚本为 `deploy.sh`，执行即可快速部署。
