# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
# Gunicorn configuration for gevent async worker

import multiprocessing
import os

# ============================================
# Server Socket
# ============================================
bind = "127.0.0.1:9001"
backlog = 2048

# ============================================
# Worker Processes - gevent 配置
# ============================================
# 【关键】使用 gevent worker 实现异步非阻塞
worker_class = "gevent"

# 【重要】worker 数量根据 CPU 限制动态计算
def get_cpu_limit():
    """获取容器实际的 CPU 限制（支持 cgroup v1 和 v2）"""
    try:
        # 尝试 cgroup v2 (cpu.max)
        with open('/sys/fs/cgroup/cpu.max', 'r') as f:
            content = f.read().strip()
            if content != 'max':
                quota, period = map(int, content.split())
                if quota > 0 and period > 0:
                    return max(1, quota // period)
    except:
        pass
    
    try:
        # 回退到 cgroup v1
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us', 'r') as f:
            quota = int(f.read().strip())
        with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us', 'r') as f:
            period = int(f.read().strip())
        if quota > 0 and period > 0:
            return max(1, quota // period)
    except:
        pass
    
    # 最后回退：环境变量或 cpu_count
    return int(os.environ.get('GUNICORN_WORKERS', multiprocessing.cpu_count()))

workers = get_cpu_limit()

# 每个 worker 的并发连接数
# gevent 基于协程，单个 worker 可处理大量并发连接
worker_connections = 10000

# 【关键】preload_app 必须为 False（gevent 要求）
# 猴子补丁需要在子进程中执行
preload_app = False

# ============================================
# Worker Lifecycle
# ============================================
# 每个 worker 处理多少请求后重启（防止内存泄漏）
max_requests = 10000
max_requests_jitter = 1000

# Worker 超时设置
timeout = 300
graceful_timeout = 30
keepalive = 5

# ============================================
# Logging
# ============================================
accesslog = "-"  # 输出到 stdout
errorlog = "-"   # 输出到 stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ============================================
# Process Naming
# ============================================
proc_name = "spug_api"

# ============================================
# Server Mechanics
# ============================================
# 守护进程模式（由 supervisor 管理，不需要）
daemon = False

# PID 文件
# 【修复】禁用 PID 文件，避免 Supervisor 重启时出现 "Already running" 错误
# Supervisor 已经管理了进程生命周期，不需要 Gunicorn 自己维护 PID 文件
pidfile = None

# ============================================
# SSL（如需要）
# ============================================
# keyfile = "/path/to/keyfile"
# certfile = "/path/to/certfile"

# ============================================
# Hooks
# ============================================
def on_starting(server):
    """服务器启动时调用"""
    pass

def on_reload(server):
    """重新加载配置时调用"""
    pass

def when_ready(server):
    """服务器准备好接收请求时调用"""
    pass

def worker_int(worker):
    """Worker 收到 SIGINT 或 SIGQUIT 时调用"""
    pass

def worker_abort(worker):
    """Worker 收到 SIGABRT 时调用"""
    pass
