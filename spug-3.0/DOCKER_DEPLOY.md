# Spug 运维平台 - Docker 部署指南

## 📋 目录

1. [快速开始](#快速开始)
2. [生产环境部署](#生产环境部署)
3. [Dockerfile 说明](#dockerfile-说明)
4. [常见问题](#常见问题)
5. [备份与恢复](#备份与恢复)

---

## 快速开始

### 1. 一键启动（适合快速体验）

```bash
# 克隆项目
git clone https://github.com/openspug/spug.git
cd spug

# 创建环境配置文件
cp .env.example .env

# 启动服务
docker-compose up -d

# 等待启动完成（约30秒）
sleep 30

# 查看日志
docker-compose logs -f

# 访问 http://localhost
# 默认账号: admin / admin123
```

---

## 生产环境部署

### 1. 系统要求

| 项目 | 最低配置 | 推荐配置 |
|------|---------|---------|
| CPU | 2核 | 4核+ |
| 内存 | 4GB | 8GB+ |
| 磁盘 | 50GB | 100GB+ SSD |
| 系统 | CentOS 7/8, Ubuntu 18.04/20.04/22.04 |

### 2. 安装 Docker

```bash
# CentOS
sudo yum install -y docker-ce docker-ce-cli containerd.io
sudo systemctl enable --now docker

# Ubuntu
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker

# 验证
docker --version  # 要求 20.10+
docker-compose --version  # 要求 1.29+ 或 v2.x
```

### 3. 部署步骤

#### 步骤 1: 准备部署目录

```bash
# 创建部署目录
mkdir -p /opt/spug
cd /opt/spug

# 上传项目文件
# 方式1: git 克隆
git clone https://github.com/openspug/spug.git .

# 方式2: 上传压缩包
# scp spug.tar.gz root@server:/opt/spug/
# tar -xzf spug.tar.gz
```

#### 步骤 2: 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置文件（必须修改以下配置）
vim .env

# 修改内容示例:
MYSQL_ROOT_PASSWORD=YourStrongRootPassword123
MYSQL_PASSWORD=YourStrongPassword123
SECRET_KEY=$(openssl rand -base64 50)
ALLOWED_HOSTS=spug.yourcompany.com,192.168.1.100
DEBUG=False
```

**⚠️ 安全提醒：生产环境必须修改默认密码！**

#### 步骤 3: 创建数据卷

```bash
# 创建 Docker 数据卷（持久化存储）
docker volume create spug-mysql-data
docker volume create spug-data
docker volume create spug-repos
docker volume create spug-logs
```

#### 步骤 4: 构建并启动

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看启动状态
docker-compose ps
```

#### 步骤 5: 验证部署

```bash
# 查看日志
docker-compose logs -f spug

# 等待出现以下信息表示启动成功:
# "Spug 运维平台启动完成"
# "访问地址: http://localhost"
# "默认账号: admin / admin123"

# 访问测试
curl http://localhost/api/account/user/
```

---

## Dockerfile 说明

### 多阶段构建架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Dockerfile.optimized                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Stage 1: frontend-builder                                  │
│  ├── 基础: node:16-alpine                                   │
│  ├── 安装 npm 依赖                                          │
│  └── 构建前端静态文件 (npm run build)                        │
│                         ↓                                   │
│  Stage 2: backend-builder                                   │
│  ├── 基础: python:3.9-slim                                  │
│  ├── 安装编译依赖 (gcc, mysql-dev)                          │
│  └── 安装 Python 依赖 (pip install)                          │
│                         ↓                                   │
│  Stage 3: production (最终镜像)                              │
│  ├── 基础: python:3.9-slim                                  │
│  ├── 安装运行时依赖 (nginx, redis, ssh...)                   │
│  ├── 从前端阶段复制构建产物                                  │
│  ├── 从后端阶段复制 Python 依赖                              │
│  └── 启动服务 (supervisord)                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 与原版 Dockerfile 的改进

| 改进项 | 原版 | 优化版 |
|--------|------|--------|
| 前端构建缓存 | 每次重新安装依赖 | 利用 Docker 缓存层 |
| npm 镜像 | 默认 | 淘宝镜像加速 |
| pip 镜像 | 清华镜像 | 清华镜像 + 缓存优化 |
| 时区设置 | 上海时区 | 上海时区 + locale |
| 健康检查 | 有 | 更完善的检查 |
| 日志输出 | 无特殊处理 | 支持日志卷挂载 |
| Celery 支持 | 无 | docker-compose 可选配置 |

---

## 常用命令

### 服务管理

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose stop

# 重启服务
docker-compose restart

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f
docker-compose logs -f spug  # 只看 Spug 服务

# 完全删除（包括数据卷！慎用）
docker-compose down -v
```

### 进入容器

```bash
# 进入 Spug 容器
docker exec -it spug bash

# 进入数据库容器
docker exec -it spug-db mysql -uroot -p

# 查看 Spug 版本
docker exec spug cat /data/spug/spug_api/spug/settings.py | grep VERSION
```

### 数据备份

```bash
# 备份数据库
docker exec spug-db mysqldump -uroot -p spug > backup_$(date +%Y%m%d).sql

# 备份文件
tar -czf spug_backup_$(date +%Y%m%d).tar.gz /var/lib/docker/volumes/spug-
```

---

## 常见问题

### Q1: 启动后无法访问

**排查步骤：**

```bash
# 1. 检查容器状态
docker-compose ps

# 2. 查看日志
docker-compose logs -f spug

# 3. 检查端口是否被占用
netstat -tlnp | grep 80

# 4. 检查防火墙
iptables -L -n | grep 80
```

**常见原因：**
- 数据库未就绪：等待 30 秒后重试
- 端口被占用：修改 docker-compose.yml 端口映射
- 内存不足：增加服务器内存或调整资源限制

### Q2: 如何修改默认账号密码

```bash
# 进入容器
docker exec -it spug bash

# 进入 Django shell
cd /data/spug/spug_api
python manage.py shell

# 修改密码
from django.contrib.auth import get_user_model
User = get_user_model()
user = User.objects.get(username='admin')
user.set_password('NewPassword123')
user.save()
exit()
```

### Q3: 如何升级版本

```bash
# 1. 备份数据
docker exec spug-db mysqldump -uroot -p spug > backup_before_upgrade.sql

# 2. 拉取最新代码
git pull origin main

# 3. 重新构建
docker-compose build --no-cache

# 4. 重启服务
docker-compose up -d

# 5. 执行迁移
docker exec spug python /data/spug/spug_api/manage.py migrate
```

### Q4: 如何配置 HTTPS

```bash
# 1. 准备 SSL 证书
mkdir -p certs
cp your_domain.crt certs/
cp your_domain.key certs/

# 2. 修改 nginx 配置
vim config/nginx.conf

# 在 server 块中添加:
server {
    listen 443 ssl;
    server_name your_domain.com;
    
    ssl_certificate /etc/nginx/certs/your_domain.crt;
    ssl_certificate_key /etc/nginx/certs/your_domain.key;
    
    # ... 其他配置
}

# 3. 重启服务
docker-compose restart spug
```

### Q5: 性能优化建议

```yaml
# docker-compose.yml 中调整资源限制
services:
  spug:
    deploy:
      resources:
        limits:
          cpus: '4'      # 根据服务器调整
          memory: 4G     # 根据服务器调整
        reservations:
          cpus: '1'
          memory: 1G
```

---

## 备份与恢复

### 自动备份脚本

```bash
#!/bin/bash
# backup.sh - 自动备份脚本

BACKUP_DIR="/opt/backups/spug"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份数据库
echo "备份数据库..."
docker exec spug-db mysqldump -uroot -p${MYSQL_ROOT_PASSWORD} spug > $BACKUP_DIR/db_$DATE.sql

# 备份文件
echo "备份文件..."
tar -czf $BACKUP_DIR/files_$DATE.tar.gz -C /var/lib/docker/volumes spug-

# 清理旧备份
echo "清理 $RETENTION_DAYS 天前的备份..."
find $BACKUP_DIR -name "*.sql" -mtime +$RETENTION_DAYS -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete

echo "备份完成: $BACKUP_DIR"
```

### 恢复数据

```bash
#!/bin/bash
# restore.sh - 恢复脚本

BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
    echo "用法: $0 <备份文件.sql>"
    exit 1
fi

# 停止服务
docker-compose stop spug

# 恢复数据库
docker exec -i spug-db mysql -uroot -p${MYSQL_ROOT_PASSWORD} spug < $BACKUP_FILE

# 启动服务
docker-compose start spug

echo "恢复完成"
```

---

## 附录

### 文件结构

```
spug/
├── docker-compose.yml          # Docker Compose 配置
├── Dockerfile.optimized        # 优化版 Dockerfile
├── .env.example                # 环境变量模板
├── .env                        # 环境变量（自己创建）
├── config/
│   └── docker/
│       ├── entrypoint.sh       # 容器启动脚本
│       ├── nginx.conf          # Nginx 配置
│       └── supervisord.conf    # Supervisor 配置
├── spug_api/                   # 后端代码
└── spug_web/                   # 前端代码
```

### 端口说明

| 端口 | 用途 | 备注 |
|------|------|------|
| 80 | HTTP | 可修改为其他端口 |
| 443 | HTTPS | 需要配置 SSL 证书 |
| 3306 | MySQL | 仅内部使用，可映射到宿主机 |

### 版本信息

- Docker: 20.10+
- Docker Compose: 1.29+ / v2.x
- Python: 3.9
- Node.js: 16
- MariaDB: 10.8

---

**文档版本**: v1.0  
**更新日期**: 2024年  
**维护团队**: Spug Dev Team
