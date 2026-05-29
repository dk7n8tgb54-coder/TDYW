# 通导运维平台部署包说明

## 部署包目录结构

```
spug-deploy-package/
├── config/                      # 配置文件
│   ├── docker-compose.yml         # Docker容器配置
│   ├── settings.py              # 后端配置（允许的IP、数据库等）
│   └── nginx.conf              # Nginx配置（如有）
│
├── backend/                     # 后端代码
│   ├── apps/                   # 应用模块
│   │   ├── account/            # 账户管理
│   │   ├── document/           # 文档管理
│   │   ├── exec/               # 执行管理
│   │   ├── home/               # 首页
│   │   └── ...（其他模块）
│   ├── libs/                   # 公共库
│   ├── spug/                  # 配置文件
│   │   └── settings.py        # Django设置
│   ├── manage.py               # Django管理脚本
│   └── requirements.txt        # Python依赖
│
├── frontend/                    # 前端构建产物
│   ├── index.html
│   ├── favicon.ico
│   ├── logo.png
│   ├── static/                 # 静态资源
│   │   ├── css/
│   │   ├── js/
│   │   └── media/
│   └── resource/              # 资源文件
│       ├── gitee.png
│       ├── gitlab.png
│       ├── grafana.png
│       ├── prometheus.png
│       └── wiki.png
│
├── scripts/                     # 部署和备份脚本
│   ├── backup_db.sh            # 数据库备份脚本
│   ├── remote_backup.sh         # 异地备份脚本
│   └── deploy.sh              # 一键部署脚本
│
├── data/                       # 数据目录（运行时挂载）
│   ├── mysql/                 # MySQL数据卷
│   ├── repos/                 # 代码仓库
│   └── documents/             # 文档文件存储
│
├── docs/                       # 部署文档
│   ├── 部署指南.md
│   └── 数据库初始化指南.md
│
└── README.md                   # 部署包说明
```

## 必备文件清单

### 1. 后端文件

#### 核心代码
- `apps/` - 所有应用模块
  - `apps/account/` - 账户和权限管理
  - `apps/document/` - 文档管理（你的主要功能）
  - `apps/exec/` - 执行管理
  - `apps/home/` - 首页组件
  - `apps/system/` - 系统管理

#### 配置文件
- `spug/settings.py` - **必须修改 ALLOWED_HOSTS**
- `requirements.txt` - Python依赖包

#### 数据库相关
- `spug/urls.py` - 路由配置

### 2. 前端文件

#### 构建产物（通过 npm run build 生成）
- `index.html` - 入口文件
- `static/` - 静态资源（CSS、JS、图片）
- `favicon.ico` - 网站图标
- `logo.png` - Logo文件
- `resource/` - 资源文件（导航图标等）

### 3. 配置文件

#### Docker配置
- `docker-compose.yml` - 容器编排配置

#### 数据库初始化
- `data/backend/init.sql` - 数据库初始化SQL（如有）

### 4. 部署脚本

#### 备份脚本
- `backup_db.sh` - 本地数据库备份
- `remote_backup.sh` - 异地备份

#### 部署脚本
- `deploy.sh` - 一键部署（可选）

### 5. 文档

- `DEPLOY_README.md` - 部署说明
- `数据库初始化指南.md` - 数据库创建指南

## 部署前准备

### 1. 修改配置

#### 后端配置（settings.py）
```python
# 修改 ALLOWED_HOSTS
ALLOWED_HOSTS = ['*', 'your-server-ip', 'your-domain.com']
```

#### 数据库密码
```yaml
# docker-compose.yml
environment:
  - MYSQL_PASSWORD=your_secure_password  # 修改为强密码
```

### 2. 前端构建

```bash
cd spug_web
npm run build
# 构建产物在 spug_web/build/ 目录
```

### 3. 准备目录

```bash
# 创建必要目录
mkdir -p data/mysql
mkdir -p data/repos
mkdir -p data/backend/documents
mkdir -p backups
```

## 部署步骤

### 方式一：Docker部署（推荐）

```bash
# 1. 上传部署包到服务器
scp -r spug-deploy-package user@server:/opt/

# 2. 进入目录
cd /opt/spug-deploy-package

# 3. 启动容器
docker-compose up -d

# 4. 查看日志
docker-compose logs -f
```

### 方式二：手动部署

```bash
# 1. 启动数据库
docker run -d --name spug-db \
  -v /opt/spug/data/mysql:/var/lib/mysql \
  -e MYSQL_DATABASE=spug \
  -e MYSQL_USER=spug \
  -e MYSQL_PASSWORD=spug.cc \
  registry.cn-hangzhou.aliyuncs.com/openspug/mariadb:10.8.2

# 2. 启动后端
docker run -d --name spug-api \
  --link spug-db:db \
  -v /opt/spug/data/backend:/data/spug/spug_api \
  -p 8000:80 \
  registry.cn-hangzhou.aliyuncs.com/openspug/spug-service

# 3. 部署前端到Web服务器（Nginx）
cp -r frontend/* /var/www/html/
```

## 数据备份策略

### 本地备份（每天凌晨2点）
```bash
crontab -e
0 2 * * * /opt/spug/scripts/backup_db.sh >> /var/log/backup.log 2>&1
```

### 异地备份（每天凌晨3点）
```bash
crontab -e
0 3 * * * /opt/spug/scripts/remote_backup.sh >> /var/log/remote_backup.log 2>&1
```

## 端口说明

| 服务 | 端口 | 说明 |
|------|------|------|
| Web服务 | 80 | HTTP访问端口 |
| 数据库 | 3306/3307 | MySQL数据库端口 |
| SSH | 22 | 远程管理端口 |

## 环境要求

- Docker 20.10+
- Docker Compose 1.29+
- Linux系统（推荐 CentOS 7+ / Ubuntu 18.04+）
- 内存: 建议 4GB+
- 硬盘: 建议 50GB+

## 注意事项

1. **生产环境务必修改密码**
   - MySQL root密码
   - MySQL用户密码
   - Django SECRET_KEY

2. **配置ALLOWED_HOSTS**
   - 不要使用 `['*']` 在生产环境
   - 明确指定服务器IP或域名

3. **数据安全**
   - 定期备份数据库
   - 配置异地备份
   - 监控备份任务执行

4. **文件存储**
   - `data/backend/documents/` 目录需要足够空间
   - 考虑使用NAS或对象存储

## 故障排查

### 容器无法启动
```bash
docker-compose logs
docker ps -a
```

### 数据库连接失败
```bash
docker exec -it spug-db mysql -uspug -p
```

### 前端无法访问后端
- 检查 `ALLOWED_HOSTS` 配置
- 检查防火墙设置
- 检查Nginx配置

## 联系支持

如有问题，请查看：
- 项目文档: https://spug.cc
- 技术支持: [联系方式]
