# Django settings.py 配置文件说明

## 文件路径
```
e:/TDYW/spug-3.0/spug_api/spug/settings.py
```

## 主要功能

这个文件是 Spug 系统的核心配置文件，控制整个 Django 应用的运行方式。

---

## 配置项详解

### 1. 基础配置（第 17-33 行）

```python
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```
- 定义项目的基础目录路径

```python
SECRET_KEY = 'vk0do47)egwzz!uk49%(y3s(fpx4+ha@ugt-hcv&%&d@hwr&p7'
```
- Django 加密密钥，用于密码加密、session 等安全功能
- 生产环境中应该保密

```python
DEBUG = True
```
- 调试模式
- `True`: 开发模式，显示详细错误信息
- `False`: 生产模式，不显示错误详情

---

### 2. 日志配置（第 35-64 行）

```python
LOGGING = {
    'version': 1,
    'formatters': {...},
    'handlers': {...},
    'loggers': {...}
}
```
- 配置日志输出格式和级别
- 所有日志输出到控制台
- 包括 `django` 和 root logger
- 日志级别为 `INFO`

---

### 3. 允许的主机（第 66 行）

```python
ALLOWED_HOSTS = ['127.0.0.1']
```
- 允许访问的主机列表
- 目前只允许本地访问 `127.0.0.1`
- 如需远程访问，需要添加域名或IP

---

### 4. 已安装的应用（第 70-83 行）

```python
INSTALLED_APPS = [
    'apps.account',        # 用户权限管理
    'apps.host',          # 主机管理
    'apps.setting',       # 系统设置
    'apps.exec',         # 运行管理（包含日志、故障、干扰等）
    'apps.schedule',      # 任务调度
    'apps.config',       # 配置管理
    'apps.app',          # 应用管理
    'apps.notify',       # 通知管理
    'apps.repository',   # 仓库管理
    'apps.home',        # 工作台
    'apps.document',    # 文档管理
    'channels',         # WebSocket支持
]
```
- 列出所有启用的 Django 应用（模块）
- 每个应用对应一个功能模块

---

### 5. 中间件（第 85-90 行）

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',     # 安全中间件
    'django.middleware.common.CommonMiddleware',       # 通用中间件
    'libs.middleware.AuthenticationMiddleware',        # 认证中间件（自定义）
    'libs.middleware.HandleExceptionMiddleware',       # 异常处理中间件（自定义）
]
```
- 请求和响应处理的中间件链
- 自定义了认证和异常处理逻辑

---

### 6. URL 配置（第 92-95 行）

```python
ROOT_URLCONF = 'spug.urls'      # HTTP路由配置
ASGI_APPLICATION = 'spug.routing.application'  # WebSocket路由配置
```

---

### 7. 数据库配置（第 97-116 行）★ 最重要的配置

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('MYSQL_DATABASE', 'spug'),
        'USER': os.environ.get('MYSQL_USER', 'spug'),
        'PASSWORD': os.environ.get('MYSQL_PASSWORD', 'spug.cc'),
        'HOST': os.environ.get('MYSQL_HOST', '127.0.0.1'),
        'PORT': os.environ.get('MYSQL_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    }
}
```

**说明**:
- 数据库引擎: MySQL
- 所有参数都从环境变量读取，如果没有则使用默认值
- **Docker 环境**:
  - `MYSQL_HOST` = `db` (容器名)
  - 由 docker-compose.yml 设置环境变量
- **本地开发环境**:
  - `MYSQL_HOST` = `127.0.0.1` (本地MySQL)
  - 需要本地安装MySQL服务

**环境变量优先级**:
1. 环境变量（Docker 或系统环境）
2. 配置文件中的默认值

**日志输出**（第 118-125 行）:
- 启动时会打印数据库连接信息
- 帮助调试数据库连接问题

---

### 8. Redis 缓存配置（第 127-146 行）

```python
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
        ...
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("127.0.0.1", 6379)],
            ...
        }
    }
}
```

**功能**:
- `CACHES`: Redis 作为缓存后端
  - 存储权限缓存、用户session等
- `CHANNEL_LAYERS`: Redis 作为 WebSocket 消息通道
  - 用于实时通信（如日志推送、通知）

**Redis 地址**:
- `127.0.0.1:6379` (容器内部)
- Redis 运行在 spug 容器内部

---

### 9. 其他配置（第 156-164 行）

```python
TOKEN_TTL = 8 * 3600                    # 访问令牌有效期（8小时）
SCHEDULE_KEY = 'spug:schedule'          # 任务调度Key
SCHEDULE_WORKER_KEY = 'spug:schedule:worker'
EXEC_WORKER_KEY = 'spug:exec:worker'
REQUEST_KEY = 'spug:request'
BUILD_KEY = 'spug:build'
REPOS_DIR = os.path.join(..., 'repos')  # 代码仓库目录
BUILD_DIR = os.path.join(REPOS_DIR, 'build')
TRANSFER_DIR = os.path.join(BASE_DIR, 'storage', 'transfer')  # 文件传输临时目录
```

---

### 10. 国际化配置（第 166-177 行）

```python
LANGUAGE_CODE = 'en-us'      # 默认语言（虽然界面是中文）
TIME_ZONE = 'Asia/Shanghai'  # 时区（北京时间）
USE_I18N = True             # 启用国际化
USE_L10N = True             # 启用本地化
USE_TZ = False              # 不使用时区转换
```

---

### 11. 认证排除（第 179-183 行）

```python
AUTHENTICATION_EXCLUDES = (
    '/account/login/',        # 登录页面不需要认证
    '/setting/basic/',       # 基本设置API
    re.compile('/apis/.*'),  # 所有API接口
)
```
- 定义不需要登录就能访问的路径

---

### 12. Spug 版本（第 185 行）

```python
SPUG_VERSION = 'v3.3.3'
```

---

### 13. 配置覆盖机制（第 187-196 行）

```python
try:
    from spug.overrides import *
    logger.info('Database settings overridden from spug.overrides')
except ImportError:
    logger.info('Using default database settings (MySQL)')
```

**功能**:
- 允许在运行时覆盖配置
- 如果存在 `spug/overrides.py` 文件，会覆盖默认配置
- 通常用于特殊部署场景

---

### 14. 数据库连接汇总（第 198-213 行）

```python
logger.info('='*50)
logger.info('DATABASE CONNECTION SUMMARY')
logger.info('='*50)
logger.info(f'Engine: {DATABASES["default"]["ENGINE"]}')
logger.info(f'Host: {DATABASES["default"].get("HOST")}')
logger.info(f'Port: {DATABASES["default"].get("PORT")}')
logger.info(f'Database: {DATABASES["default"].get("NAME")}')
logger.info(f'User: {DATABASES["default"].get("USER")}')
```

**功能**:
- 启动时打印数据库连接信息
- 帮助开发者确认数据库配置是否正确
- 提示 Docker 环境的注意事项

---

## 关键配置说明

### Docker 环境数据库连接

**docker-compose.yml 设置的环境变量**:
```yaml
environment:
  - MYSQL_DATABASE=spug
  - MYSQL_USER=spug
  - MYSQL_PASSWORD=spug.cc
  - MYSQL_HOST=db          # 容器名
  - MYSQL_PORT=3306
```

**settings.py 读取环境变量**:
```python
HOST = os.environ.get('MYSQL_HOST', '127.0.0.1')
```

**实际连接**:
- Django 通过 `db:3306` 连接到 spug-db 容器
- 容器间通过 Docker 网络通信

---

## 配置文件的作用总结

1. **定义数据库连接**: 告诉 Django 如何连接数据库
2. **配置缓存**: 设置 Redis 用于缓存和消息队列
3. **启用应用**: 列出所有功能模块
4. **设置中间件**: 配置请求处理流程
5. **控制日志**: 定义日志输出格式
6. **安全设置**: 配置密钥、允许的主机
7. **国际化**: 设置时区和语言
8. **路径配置**: 定义各种目录路径

---

## 如何修改配置

### 1. 修改数据库连接
**方式一**: 修改环境变量（推荐）
```bash
# 在 docker-compose.yml 中修改
environment:
  - MYSQL_HOST=your-db-host
```

**方式二**: 修改默认值
```python
# 在 settings.py 中修改默认值
DATABASES = {
    'default': {
        'HOST': 'your-db-host',  # 修改这里
        ...
    }
}
```

### 2. 切换到 SQLite
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',  # 改为 SQLite
        'NAME': 'spug.db',
    }
}
```

### 3. 使用配置覆盖
创建 `spug/overrides.py`:
```python
# 覆盖数据库配置
DATABASES['default']['HOST'] = 'custom-host'
DATABASES['default']['PASSWORD'] = 'custom-password'
```

---

## 调试技巧

### 查看数据库连接信息
启动服务后查看日志：
```bash
docker logs spug
```

输出示例：
```
DATABASE CONNECTION SUMMARY
==================================================
Engine: django.db.backends.mysql
Host: db
Port: 3306
Database: spug
User: spug
==================================================
```

### 切换调试模式
```python
DEBUG = False  # 生产环境
DEBUG = True   # 开发环境（显示详细错误）
```

---

## 重要提示

1. **不要泄露 SECRET_KEY**: 生产环境中应该使用环境变量设置

2. **数据库连接**: Docker 环境使用容器名 `db`，本地开发使用 `127.0.0.1`

3. **Redis 配置**: Redis 运行在 spug 容器内部，使用 `127.0.0.1:6379`

4. **日志级别**: 开发时可改为 `DEBUG`，生产环境保持 `INFO`

5. **环境变量优先**: 任何通过环境变量设置的配置都会覆盖默认值

---

## 配置文件流程图

```
Django 启动
    ↓
读取 settings.py
    ↓
检查环境变量 (MYSQL_HOST, MYSQL_PASSWORD等)
    ↓
检查 overrides.py
    ↓
应用配置
    ↓
打印数据库连接信息
    ↓
Django 运行
```

---

## 总结

`settings.py` 是 Spug 系统的大脑，控制着：

- ✅ 数据库连接
- ✅ 缓存系统
- ✅ 模块加载
- ✅ 安全设置
- ✅ 日志输出
- ✅ 中间件
- ✅ 时区语言
- ✅ 路径配置

所有这些配置都会在 Django 启动时生效，影响整个系统的运行方式。
