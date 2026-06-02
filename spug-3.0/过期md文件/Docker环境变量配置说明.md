# Docker 环境变量配置说明

## 📋 概述

项目使用`.env`文件管理敏感配置，避免在`docker-compose.yml`中硬编码密码。

---

## 📁 文件结构

```
spug-3.0/
├── .env                    # 实际使用的环境变量（包含敏感信息，已加入.gitignore）
├── .env.example            # 环境变量模板（可提交到版本控制）
├── docker-compose.yml      # Docker Compose配置（引用.env变量）
└── .gitignore             # Git忽略配置（包含.env）
```

---

## 🔧 配置方法

### 开发环境

**1. 复制模板文件**
```bash
cp .env.example .env
```

**2. 修改密码（可选）**
```bash
# 编辑 .env 文件
MYSQL_ROOT_PASSWORD=your_secure_password
MYSQL_PASSWORD=your_secure_password
```

**3. 启动服务**
```bash
docker-compose up -d
```

### 生产环境部署

**1. 修改密码为强密码**
```bash
# 生成随机密码
openssl rand -base64 32

# 编辑 .env 文件
MYSQL_ROOT_PASSWORD=<生成的强密码>
MYSQL_PASSWORD=<生成的强密码>
DJANGO_SECRET_KEY=<生成的密钥>
```

**2. 配置文件示例**
```env
# 数据库配置
MYSQL_DATABASE=spug
MYSQL_USER=spug
MYSQL_PASSWORD=xK9#mP2$vL8@nQ5&wR7
MYSQL_ROOT_PASSWORD=yJ4*oN6!zQ9%cP2$tX3

# Django配置
DJANGO_SECRET_KEY=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0
```

**3. 启动服务**
```bash
docker-compose up -d
```

---

## 🔒 安全最佳实践

### 1. 环境变量隔离

**开发环境**:
```bash
# .env 包含弱密码
MYSQL_ROOT_PASSWORD=spug.cc
```

**生产环境**:
```bash
# .env 包含强密码
MYSQL_ROOT_PASSWORD=$(openssl rand -base64 32)
```

### 2. Git 保护

**.gitignore 配置**:
```
# 敏感配置文件
.env
.env.local
.env.production

# 数据备份
backups/*.sql
backups/*.zip
emergency_backup.sql
```

### 3. 密码管理策略

**密码复杂度要求**:
- 最少16个字符
- 包含大小写字母
- 包含数字和特殊符号
- 避免使用常见密码

**密码更新频率**:
- 开发环境：无要求
- 生产环境：每3-6个月更新一次
- 发现泄露时立即更新

---

## 📝 docker-compose.yml 配置说明

### 健康检查配置

```yaml
healthcheck:
  test: ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -u root -p${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD not set} || exit 1"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

**关键点**:
- ✅ 使用`CMD-SHELL`环境，`$MYSQL_ROOT_PASSWORD`会正确展开
- ✅ `:?MYSQL_ROOT_PASSWORD not set`确保变量未设置时报错
- ✅ 使用`127.0.0.1`而非`localhost`，避免Socket认证问题

### 环境变量引用

```yaml
environment:
  - MYSQL_DATABASE=${MYSQL_DATABASE}
  - MYSQL_USER=${MYSQL_USER}
  - MYSQL_PASSWORD=${MYSQL_PASSWORD}
  - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
```

**优势**:
- ✅ 密码存储在`.env`文件中，便于管理
- ✅ 不同环境可以使用不同的`.env`文件
- ✅ 不会泄露到版本控制系统

---

## 🚀 部署场景示例

### 场景1: 开发环境到生产环境

**步骤**:
```bash
# 1. 开发环境配置 .env.dev
cp .env.example .env.dev
# 编辑 .env.dev，设置开发环境密码

# 2. 生产环境配置 .env.prod
cp .env.example .env.prod
# 编辑 .env.prod，设置生产环境强密码

# 3. 开发环境启动
docker-compose --env-file .env.dev up -d

# 4. 生产环境启动
docker-compose --env-file .env.prod up -d
```

### 场景2: 多租户部署

**步骤**:
```bash
# 1. 租户A配置
cp .env.example .env.tenant-a
docker-compose --project-name spug-a --env-file .env.tenant-a up -d

# 2. 租户B配置
cp .env.example .env.tenant-b
docker-compose --project-name spug-b --env-file .env.tenant-b up -d
```

---

## 🔍 故障排查

### 问题1: 健康检查失败

**症状**: 容器状态为`unhealthy`

**排查**:
```bash
# 检查环境变量
docker exec spug-db env | grep MYSQL

# 手动测试健康检查命令
docker exec spug-db mysqladmin ping -h 127.0.0.1 -u root -p${MYSQL_ROOT_PASSWORD}

# 查看容器日志
docker logs spug-db --tail 50
```

**解决**:
- 确保`.env`文件存在
- 确保`MYSQL_ROOT_PASSWORD`已设置
- 重启容器：`docker-compose restart db`

### 问题2: 环境变量未生效

**症状**: 容器使用默认配置

**排查**:
```bash
# 检查docker-compose.yml配置
cat docker-compose.yml | grep environment

# 检查.env文件
cat .env

# 检查容器内环境变量
docker exec spug-db env | grep MYSQL
```

**解决**:
- 确保`docker-compose.yml`使用`${VAR}`格式
- 确保`.env`文件在`docker-compose.yml`同一目录
- 重新创建容器：`docker-compose up -d --force-recreate`

---

## 📊 配置对比

| 配置方式 | 优点 | 缺点 | 适用场景 |
|---------|------|------|---------|
| 硬编码在docker-compose.yml | 简单直接 | 安全性差、难以管理 | 测试环境 |
| 使用.env文件 | 灵活、安全、易管理 | 需要额外文件 | ✅ 推荐：所有环境 |
| 使用Docker Secrets | 安全性最高 | 配置复杂、需要Swarm | 生产环境大集群 |

---

## ✅ 总结

**当前配置**:
- ✅ 使用`.env`文件管理环境变量
- ✅ 健康检查正确引用环境变量
- ✅ 已添加`.gitignore`保护敏感信息
- ✅ 生产环境可轻松修改密码

**生产环境部署步骤**:
1. 复制`.env.example`为`.env`
2. 修改密码为强密码
3. 运行`docker-compose up -d`
4. 验证健康检查状态：`docker ps`

**安全性评估**: 🟢 高
- 密码不硬编码
- 环境变量隔离
- Git保护完善
- 支持多环境配置
