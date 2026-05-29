# gevent 异步 Worker 部署检查报告

**检查时间：** 2026-04-01 15:11  
**容器：** tdyw  
**状态：** ✅ 部署成功

---

## 一、核心组件检查

### 1.1 gevent 安装 ✅

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 版本 | 24.2.1 | ✅ 符合 requirements.txt 要求 |
| 依赖 | greenlet 3.3.2, zope.event 6.1 | ✅ 自动安装 |
| 兼容性 | Python 3.10.12 | ✅ 完全兼容 |

### 1.2 Gunicorn 进程检查 ✅

| 检查项 | 结果 | 说明 |
|--------|------|------|
| Master 进程 | 1 个 | PID 9 |
| Worker 进程 | 4 个 | PID 43, 44, 45, 46 |
| 总数 | 5 个 | ✅ 与 CPU 限制（4核）匹配 |
| 配置文件 | gunicorn.conf.py | ✅ 已使用 |

**进程详情：**
```
/usr/bin/python3 /usr/local/bin/gunicorn -c gunicorn.conf.py spug.wsgi
```

---

## 二、配置文件检查

### 2.1 gunicorn.conf.py ✅

| 配置项 | 值 | 状态 | 说明 |
|--------|-----|------|------|
| worker_class | "gevent" | ✅ | 使用 gevent 异步 worker |
| workers | 4 | ✅ | 根据 cgroup 动态计算 |
| worker_connections | 10000 | ✅ | 每个 worker 支持 1 万并发 |
| preload_app | False | ✅ | gevent 必需 |
| timeout | 300 | ✅ | 5 分钟超时 |
| bind | 127.0.0.1:9001 | ✅ | 本地监听 |

**CPU 限制检测逻辑：**
- 优先读取 `/sys/fs/cgroup/cpu.max` (cgroup v2)
- 回退到 `/sys/fs/cgroup/cpu/cpu.cfs_quota_us` (cgroup v1)
- 最后使用环境变量或 cpu_count()

### 2.2 wsgi.py ✅

| 检查项 | 结果 | 说明 |
|--------|------|------|
| monkey patch | ✅ | `gevent.monkey.patch_all()` 在最顶部 |
| 导入顺序 | ✅ | 在 `import os` 之前执行 |
| 注释 | ✅ | 有清晰的注释说明 |

**关键代码：**
```python
# 【关键】gevent 猴子补丁 - 必须在导入任何其他模块前执行！
import gevent.monkey
gevent.monkey.patch_all()
```

### 2.3 Nginx 配置 ✅

| 检查项 | 结果 | 说明 |
|--------|------|------|
| upstream | ✅ | `django_backend` 已配置 |
| keepalive | ✅ | 100 个长连接 |
| Host 头 | ✅ | `proxy_set_header Host $host;` 已修复 |
| proxy_http_version | ✅ | 1.1 支持 keepalive |
| proxy_read_timeout | ✅ | 300s 与 Gunicorn 一致 |

**关键配置：**
```nginx
upstream django_backend {
    server 127.0.0.1:9001;
    keepalive 100;
}

location ^~ /api/ {
    proxy_pass http://django_backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;  # 修复 400 Bad Request
    proxy_read_timeout 300s;
}
```

### 2.4 start-api.sh ✅

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 命令 | `gunicorn -c gunicorn.conf.py spug.wsgi` | ✅ 使用配置文件 |

### 2.5 settings.py ✅

| 检查项 | 结果 | 说明 |
|--------|------|------|
| CONN_MAX_AGE | 0 | ✅ gevent 兼容模式 |

---

## 三、Docker 配置检查

### 3.1 docker-compose.yml ✅

| 检查项 | 结果 | 说明 |
|--------|------|------|
| cpus | 4 | ✅ 已限制 |
| memory | 4G | ✅ 已限制 |
| ulimits | 65535 | ✅ 文件描述符限制已添加 |

**注意：** ulimits 需要重启容器才能生效

---

## 四、功能验证

### 4.1 服务状态 ✅

| 服务 | 状态 | 说明 |
|------|------|------|
| Nginx | ✅ 运行 | worker 进程 16 个 |
| Gunicorn | ✅ 运行 | 1 master + 4 workers |
| Redis | ✅ 运行 | 端口 6379 |
| Celery | ✅ 运行 | 多个 worker 进程 |

### 4.2 API 测试 ✅

| 接口 | 状态 | 说明 |
|------|------|------|
| /api/document/disk_usage/ | ✅ 200 | 正常响应 |
| /api/document/folder/ | ✅ 200 | 正常响应 |

**修复记录：**
- 15:04 修复 Host 头问题（400 Bad Request → 200 OK）

---

## 五、理论性能指标

| 指标 | 数值 | 说明 |
|------|------|------|
| Worker 数量 | 4 | 与 CPU 核心数匹配 |
| 每 Worker 连接 | 10,000 | gevent 协程支持 |
| **理论并发** | **40,000** | workers × connections |
| 超时时间 | 300s | 支持大文件上传 |

---

## 六、问题与修复

### 6.1 已修复问题

| 问题 | 原因 | 修复方案 |
|------|------|----------|
| 400 Bad Request | upstream 导致 Host 头为 "django_backend" | 添加 `proxy_set_header Host $host;` |
| Worker 数量过多 | cgroup 读取失败 | 完善 cgroup v1/v2 检测逻辑 |
| gevent 未安装 | 容器重建后丢失 | 重新执行 `pip install -r requirements.txt` |

### 6.2 待确认事项

| 事项 | 状态 | 说明 |
|------|------|------|
| ulimits 生效 | ⏳ 需重启容器 | 当前使用系统默认值 |
| 压力测试 | ⏳ 未执行 | 建议用 wrk 或 locust 测试 |

---

## 七、总结

### 7.1 部署状态：✅ 成功

所有核心组件已正确配置并运行：
- ✅ gevent 24.2.1 已安装
- ✅ wsgi.py monkey patch 已配置
- ✅ gunicorn.conf.py 异步 worker 已配置
- ✅ Nginx upstream keepalive 已配置
- ✅ Django CONN_MAX_AGE = 0 已配置
- ✅ API 响应正常（200 OK）

### 7.2 关键配置回顾

```python
# gunicorn.conf.py 核心配置
worker_class = "gevent"
workers = 4  # 根据 CPU 限制动态计算
worker_connections = 10000
preload_app = False
timeout = 300
```

```nginx
# Nginx 核心配置
upstream django_backend {
    server 127.0.0.1:9001;
    keepalive 100;
}

proxy_pass http://django_backend;
proxy_set_header Host $host;
proxy_read_timeout 300s;
```

### 7.3 下一步建议

1. **重启容器**使 ulimits 生效
2. **压力测试**验证 40,000 并发能力
3. **监控观察**确保稳定运行

---

**报告生成完毕**
