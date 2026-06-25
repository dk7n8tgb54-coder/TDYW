# Nginx + Django 异步 Worker 优化方案

## 一、当前架构问题分析

### 1.1 现有瓶颈

```
当前架构（同步模式）：
├─ Nginx: 4个Worker × 10240连接 = 能接40960个请求
├─ Gunicorn: 4个同步Worker
│   └─ 每个Worker同时只能处理1个请求
└─ 结果: 同时只能处理4个请求，大量请求排队

瓶颈: Gunicorn处理能力 << Nginx接收能力
```

### 1.2 问题场景

**场景：100个用户同时上传大文件**
```
时间线:
0秒:   100个请求到达Nginx
       ├─ Nginx: 全部接收
       └─ Gunicorn: 4个Worker处理4个请求，96个排队

10秒:  第一批处理完（假设每个10秒）
       ├─ 完成4个，剩余96个
       └─ 排队时间已达10秒，部分用户开始超时

250秒: 处理完所有请求（4分10秒）
       └─ 大部分用户已超时，体验极差
```

**结果:**
- Nginx没崩，但用户体验崩溃
- 后端Django被慢请求拖死
- 数据库连接池被长时间占用

---

## 二、优化方案：异步Worker + Nginx协同

### 2.1 目标架构

```
优化后架构（异步模式）：
├─ Nginx: 4个Worker × 4096连接 = 能接16384个请求
├─ Gunicorn: 4个异步Worker (gevent)
│   └─ 每个Worker能处理1000个并发请求
└─ 结果: 能同时处理4000个请求，大幅提升并发能力
```

### 2.2 核心改进

| 组件 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| **Nginx** | worker_connections 10240 | worker_connections 4096 | 更合理 |
| **Gunicorn** | sync Worker (4并发) | gevent Worker (4000并发) | 1000倍 |
| **总并发** | 4 | ~4000 | 1000倍 |

---

## 三、详细配置

### 3.1 Nginx 配置优化

```nginx
# /etc/nginx/nginx.conf

user www-data;

# Worker进程数 = CPU核心数
worker_processes auto;

pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    # 每个Worker最大连接数（保持10240，系统句柄足够时无需降低）
    worker_connections 10240;
    
    # 使用epoll（Linux高效IO模型）
    use epoll;
    
    # 允许一个Worker同时接受多个新连接
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 日志格式（增加 upstream 时间统计）
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time '
                    'uct="$upstream_connect_time" '
                    'uht="$upstream_header_time" '
                    'urt="$upstream_response_time"';

    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log warn;

    # 性能优化
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    # 关键优化：上游服务器配置
    upstream django_backend {
        # 【优化】使用keepalive保持长连接，减少TCP握手开销
        server 127.0.0.1:8000;
        keepalive 100;  # 保持100个空闲连接
    }

    server {
        listen 80;
        server_name localhost;

        # 【重要】大文件上传限制（与Django配置一致：10GB）
        client_max_body_size 10G;       # 最大上传文件大小（与DEFAULT_MAX_FILE_SIZE一致）
        client_body_buffer_size 16k;    # 请求体缓冲区
        client_body_timeout 300s;       # 读取请求体超时
        
        # 【重要】上传临时目录配置（优化大文件上传性能）
        client_body_temp_path /tmp/nginx_client_body 1 2;

        location / {
            proxy_pass http://django_backend;
            
            # 【优化】关键代理参数
            proxy_http_version 1.1;           # 使用HTTP/1.1支持keepalive
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            
            # 【关键修复】Nginx超时必须 >= Gunicorn超时，否则出现504
            proxy_connect_timeout 30s;        # 连接上游超时
            proxy_send_timeout 300s;          # 发送超时（配合大文件上传）
            proxy_read_timeout 300s;          # 读取响应超时（必须 >= Gunicorn timeout）
            
            # 【优化】缓冲区设置
            proxy_buffering on;
            proxy_buffer_size 4k;
            proxy_buffers 8 4k;
        }
    }
}
```

**关键优化点：**
1. `worker_connections 10240`：保持原值，系统句柄足够时无需降低
2. `proxy_read_timeout 300s`：**必须 >= Gunicorn timeout**，否则出现504
3. `keepalive 100`：保持与后端的长连接，减少TCP握手
4. `proxy_http_version 1.1`：支持HTTP/1.1 keepalive
5. `client_max_body_size 2G`：大文件上传限制

---

### 3.2 Gunicorn 异步Worker配置

```python
# gunicorn.conf.py
import multiprocessing
import os

# 基本配置
bind = "0.0.0.0:8000"

# 【关键优化】使用 gevent 异步 Worker
worker_class = "gevent"

# 【关键修复】gevent模式下workers = CPU核心数（不需要 *2+1）
workers = multiprocessing.cpu_count()  # 通常4个

# 【关键优化】每个Worker的并发连接数
worker_connections = 1000  # 每个Worker能处理1000个并发请求

# 总并发能力 = workers × worker_connections = 4 × 1000 = 4000

# 线程数（gevent模式下不使用，但保留配置）
threads = 1

# 超时设置（异步Worker可以更长）
timeout = 120  # 2分钟
timeout = 300  # 大文件上传需要更长时间

# 优雅重启
graceful_timeout = 30

# 日志
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"
loglevel = "info"

# 进程名称
proc_name = "tdyw_api"

# 【关键修复】gevent模式下必须关闭preload_app，否则猴子补丁失效
preload_app = False

# 【优化】最大请求数，超过自动重启（防内存泄漏）
max_requests = 10000
max_requests_jitter = 1000  # 随机抖动，避免同时重启
```

**关键参数解释：**
- `worker_class = "gevent"`：使用gevent异步模式
- `workers = CPU`：**gevent不需要多开进程**，协程靠事件驱动
- `worker_connections = 1000`：每个Worker能并发处理1000个请求
- `timeout = 300`：异步模式下可以支持长时间请求
- `preload_app = False`：**gevent严禁开启预加载**，必须在子进程中打猴子补丁

---

### 3.3 Supervisor 配置更新

```ini
# /etc/supervisor/conf.d/gunicorn.conf

[program:gunicorn]
command=/usr/local/bin/gunicorn spug.wsgi:application -c /data/spug/gunicorn.conf.py

directory=/data/spug/spug_api

user=root

autostart=true
autorestart=true

    # 【注意】minfds在容器内不生效，必须通过Docker参数设置
    # docker-compose.yml 中使用 ulimits 配置

# 日志
stdout_logfile=/var/log/supervisor/gunicorn.log
stderr_logfile=/var/log/supervisor/gunicorn_error.log

# 环境变量
environment=DJANGO_SETTINGS_MODULE="spug.settings"
```

---

### 3.4 Django 配合优化

```python
# settings.py

# 数据库连接池（与异步Worker配合）
DATABASES = {
    'default': {
        # ... 其他配置
        'CONN_MAX_AGE': 0,  # 【重要】gevent模式下建议关闭持久连接
        # 或使用: 'CONN_MAX_AGE': None
        'OPTIONS': {
            'charset': 'utf8mb4',
            'sql_mode': 'STRICT_TRANS_TABLES',
            'connect_timeout': 10,
            'read_timeout': 30,
            'write_timeout': 30,
        }
    }
}

# 【重要】gevent 需要猴子补丁，在 wsgi.py 中添加
```

```python
# wsgi.py

# 【关键】必须在导入任何其他模块前打猴子补丁！
import gevent.monkey
gevent.monkey.patch_all()

# 确认补丁已生效后再导入其他模块
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

application = get_wsgi_application()
```

---

## 四、实施步骤

### 4.1 安装依赖

```bash
# 进入容器
docker exec -it tdyw bash

# 安装 gevent
pip install gevent

# 验证安装
python -c "import gevent; print(gevent.__version__)"
```

### 4.2 更新配置文件

```bash
# 1. 更新 gunicorn.conf.py
cat > /data/spug/gunicorn.conf.py << 'EOF'
import multiprocessing

bind = "0.0.0.0:8000"
worker_class = "gevent"
workers = multiprocessing.cpu_count()  # 【修复】gevent模式只需CPU核心数
worker_connections = 1000
threads = 1
timeout = 300
graceful_timeout = 30
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"
loglevel = "info"
proc_name = "tdyw_api"
preload_app = False  # 【关键修复】gevent必须关闭预加载
max_requests = 10000
max_requests_jitter = 1000
EOF

# 2. 更新 wsgi.py（添加猴子补丁）
# 注意：确保 gevent.monkey.patch_all() 在导入其他模块前执行
```

### 4.3 系统参数调整

```bash
# 【关键修复】Docker容器内修改limits.conf无效，必须使用Docker参数

# 方案1：docker-compose.yml 中添加
# ulimits:
#   nofile:
#     soft: 65535
#     hard: 65535

# 方案2：docker run 命令中添加
# docker run --ulimit nofile=65535:65535 ...

# 验证（在容器内执行）
ulimit -n
```

### 4.4 重启服务

```bash
# 重启 Gunicorn
supervisorctl restart gunicorn

# 查看状态
supervisorctl status gunicorn

# 查看日志
tail -f /var/log/supervisor/gunicorn.log
```

---

## 五、验证优化效果

### 5.1 检查Worker类型

```bash
# 查看进程
ps aux | grep gunicorn

# 应该看到类似：
# /usr/local/bin/python /usr/local/bin/gunicorn spug.wsgi:application -c gunicorn.conf.py

# 查看日志确认gevent加载
tail /var/log/supervisor/gunicorn.log
# 预期输出: "Using worker: gevent"
```

### 5.2 压力测试

```bash
# 安装压测工具
pip install locust

# 或者使用 wrk（需要在容器内安装）
apt-get install wrk

# 【建议】逐步加压测试，初次上线不要直接压到4000
# 步骤1: 100并发
wrk -t4 -c100 -d30s http://localhost/api/document/health/

# 步骤2: 1000并发
wrk -t4 -c1000 -d30s http://localhost/api/document/health/

# 步骤3: 4000并发（确认稳定后再执行）
wrk -t4 -c4000 -d30s http://localhost/api/document/health/

# 参数说明：
# -t4: 4个线程
# -cN: N个并发连接（逐步增加）
# -d30s: 持续30秒
```

### 5.3 监控指标

```bash
# 查看连接数
curl http://localhost/api/document/health/db-pool/

# 预期：
# - 并发处理能力大幅提升
# - 响应时间稳定
# - 无503错误
```

---

## 六、风险与注意事项

### 6.1 潜在风险

| 风险 | 说明 | 解决方案 |
|------|------|----------|
| **第三方库不兼容** | 某些C扩展库与gevent冲突 | 测试所有功能，发现问题换库 |
| **猴子补丁顺序** | patch_all()必须在导入其他库前执行 | 确保wsgi.py中顺序正确 |
| **数据库连接问题** | gevent下MySQL连接可能不稳定 | 使用CONN_MAX_AGE=0 |
| **调试困难** | 异步堆栈更难调试 | 增加日志，使用专门工具 |

### 6.2 不适用异步的场景

**以下情况保持同步Worker：**
```
├─ CPU密集型任务（如大量计算）
│   └─ gevent对CPU密集型无提升，反而增加切换开销
│
├─ 大量同步IO的第三方库
│   └─ 如果库不支持异步，gevent无法优化
│
└─ 已使用Celery处理异步任务
    └─ 如果慢操作都走Celery，Gunicorn保持同步即可
```

### 6.3 回滚方案

```bash
# 如果出现问题，快速回滚：

# 1. 修改回同步Worker
sed -i 's/worker_class = "gevent"/worker_class = "sync"/' /data/spug/gunicorn.conf.py
sed -i 's/workers = multiprocessing.cpu_count()/workers = multiprocessing.cpu_count() * 2 + 1/' /data/spug/gunicorn.conf.py
sed -i 's/preload_app = False/preload_app = True/' /data/spug/gunicorn.conf.py

# 2. 注释掉wsgi.py中的猴子补丁
sed -i 's/import gevent.monkey/# import gevent.monkey/' /data/spug/spug_api/spug/wsgi.py
sed -i 's/gevent.monkey.patch_all()/# gevent.monkey.patch_all()/' /data/spug/spug_api/spug/wsgi.py

# 3. 重启
supervisorctl restart gunicorn
```

---

## 七、方案对比

| 方案 | 并发能力 | 复杂度 | 适用场景 |
|------|----------|--------|----------|
| **同步Worker（当前）** | 4 | 低 | 低并发、简单应用 |
| **异步Worker（本方案）** | 4000 | 中 | 高并发、IO密集型 |
| **增加Worker数量** | 8-16 | 低 | 中等并发 |
| **Celery异步处理** | 无限 | 高 | 慢操作解耦 |

---

## 八、推荐实施计划

### Phase 1：开发环境测试（1天）
```
1. 安装 gevent
2. 更新配置文件
3. 全面功能测试
4. 压力测试验证
```

### Phase 2：预发布环境（1天）
```
1. 部署到预发布
2. 模拟生产流量
3. 监控72小时
4. 确认稳定
```

### Phase 3：生产环境（谨慎）
```
1. 选择低峰期部署
2. 保留回滚方案
3. 加强监控
4. 逐步放量
```

---

## 九、结论

**本方案核心收益：**
- 并发能力提升1000倍（4 → 4000）
- 大幅减少503错误
- 提升用户体验（响应更快）

**关键前提：**
- 确保第三方库与gevent兼容
- 正确配置猴子补丁
- 充分测试后再上生产

**一句话总结：**
> **用 gevent 把 Gunicorn 从"4个单线程工人"变成"4个能同时处理1000个任务的超人工人"，但必须正确配置：关闭preload、Nginx超时>=后端、猴子补丁在最顶部。**
