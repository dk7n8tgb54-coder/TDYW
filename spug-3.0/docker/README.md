# Docker 部署说明

## 快速开始

### 1. 准备环境文件

```bash
cd docker
cp .env.example .env
vim .env  # 修改密码和配置
```

### 2. 构建并启动

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f spug
```

### 3. 访问应用

- 地址：http://localhost
- 默认账号：admin / admin123

## 目录结构

```
docker/
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker Compose 配置
├── .env.example            # 环境变量模板
├── config/
│   ├── nginx.conf          # Nginx 配置
│   ├── supervisord.conf    # Supervisor 配置
│   ├── entrypoint.sh       # 启动脚本
│   └── mysql.cnf           # MySQL 配置
└── README.md               # 本文档
```

## 常用命令

```bash
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f spug
docker-compose logs -f spug-db

# 重启服务
docker-compose restart spug

# 停止服务
docker-compose stop

# 启动服务
docker-compose start

# 删除服务（保留数据）
docker-compose down

# 删除服务和数据卷（慎用！）
docker-compose down -v

# 进入容器
docker exec -it spug bash
docker exec -it spug-db mysql -uroot -p
```

## 配置说明

### 环境变量 (.env)

- `MYSQL_ROOT_PASSWORD`: MySQL root 密码（必填）
- `MYSQL_PASSWORD`: MySQL 应用密码（必填）
- `SECRET_KEY`: Django SECRET_KEY（必填）
- `DEBUG`: 调试模式（生产环境设为 False）
- `ALLOWED_HOSTS`: 允许的主机名（逗号分隔）

### 端口映射

- `80`: HTTP 访问端口
- `3306`: MySQL 端口（仅用于备份恢复，生产环境建议不映射）

## 备份恢复

### 备份

```bash
# 备份数据库
docker exec spug-db mysqldump -uroot -p${MYSQL_ROOT_PASSWORD} spug > backup.sql

# 备份文件
docker run --rm -v spug-data:/data -v $(pwd):/backup alpine tar czf /backup/files.tar.gz /data
```

### 恢复

```bash
# 恢复数据库
docker exec -i spug-db mysql -uroot -p${MYSQL_ROOT_PASSWORD} spug < backup.sql
```

## 注意事项

1. 生产环境必须修改 `.env` 中的默认密码
2. 建议配置 HTTPS 证书
3. 定期备份数据
4. 监控磁盘空间使用情况
