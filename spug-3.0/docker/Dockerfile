
# 基础镜像
# 选择官方 Node.js 镜像作为前端构建环境
# 选择官方 Ubuntu 镜像作为后端构建和生产环境基础
# 使用多阶段构建优化镜像大小和安全性
# 1. 前端构建阶段：使用 Node.js 镜像安装依赖并构建前端
# 2. 后端构建阶段：使用 Ubuntu 镜像安装 Python 和编译依赖，安装 Python 包
# 3. 生产镜像阶段：使用 Ubuntu镜像，安装运行时依赖，复制前端构建产物和后端代码
#docker build -t tdyw:latest -f docker/Dockerfile .

# ==================== Stage 1: 前端构建 ====================
FROM m.daocloud.io/docker.io/library/node:18-alpine AS frontend-builder

# 设置工作目录
WORKDIR /app

# 复制前端代码
COPY spug_web/package.json spug_web/package-lock.json ./

# 安装依赖（利用 Docker 缓存）
RUN npm config set registry https://registry.npmmirror.com && \
    npm install

# 复制源代码
COPY spug_web/ ./

# 构建前端
RUN npm run build

# ==================== Stage 2: 后端构建 ====================
FROM ubuntu:22.04 AS backend-builder

# 安装 Python 和编译依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    python3.10-dev \
    gcc \
    g++ \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 设置 Python 命令
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# 设置工作目录
WORKDIR /app

# 复制后端代码
COPY spug_api/ ./

# 安装 Python 依赖（使用阿里云镜像加速）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r requirements.txt

# ==================== Stage 3: 生产镜像 ====================
FROM ubuntu:22.04

# 设置时区和字符集
# DEBIAN_FRONTEND=noninteractive: 抑制 tzdata 等包安装时的交互式 debconf 提示
ENV TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive

# 安装运行时依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    python3.10-dev \
    nginx \
    supervisor \
    redis-server \
    curl \
    netcat-openbsd \
    tzdata \
    libmysqlclient21 \
    libffi8 \
    libssl3 \
    default-libmysqlclient-dev \
    pkg-config \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 设置 Python 命令
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# 创建应用目录
RUN mkdir -p /data/spug /var/log/supervisor

# 设置工作目录
WORKDIR /data/spug

# 从前端构建阶段复制构建产物
COPY --from=frontend-builder /app/build ./spug_web/build

# 从后端构建阶段复制代码和依赖
COPY --from=backend-builder /app ./spug_api

# 在生产镜像阶段安装 Python 依赖
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r spug_api/requirements.txt

# 复制配置文件
COPY docker/config/nginx.conf /etc/nginx/nginx.conf
COPY docker/config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/config/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 暴露端口
EXPOSE 80

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost/api/account/user/ || exit 1

# 启动命令
ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
