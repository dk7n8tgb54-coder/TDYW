
# 基础镜像
# 选择官方 Node.js 镜像作为前端构建环境
# 选择官方 Ubuntu 镜像作为后端构建和生产环境基础
# 使用多阶段构建优化镜像大小和安全性
# 1. 前端构建阶段：使用 Node.js 镜像安装依赖并构建前端
# 2. 后端构建阶段：使用 Ubuntu 镜像安装 Python 和编译依赖，安装 Python 包
# 3. 生产镜像阶段：使用 Ubuntu镜像，安装运行时依赖，复制前端构建产物和后端代码
#docker build -t tdyw:latest -f Dockerfile .

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

# 构建前端（增加 Node 内存限制，防止打包卡顿）
RUN NODE_OPTIONS=--max_old_space_size=4096 npm run build

# ==================== Stage 2: 后端构建 ====================
FROM ubuntu:22.04 AS backend-builder

# 安装 Python 和编译依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-venv \
    python3.10-dev \
    gcc \
    g++ \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 先只拷贝依赖文件（核心优化：源码变动不会导致 pip install 缓存失效）
COPY spug_api/requirements.txt .

# 创建虚拟环境并安装依赖（隔离系统 Python，避免路径硬编码和 bin 覆盖问题）
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# 最后拷贝全部源码
COPY spug_api/ ./

# ==================== Stage 3: 生产镜像 ====================
FROM ubuntu:22.04

# 设置时区和字符集，优先使用虚拟环境的 Python 命令
ENV TZ=Asia/Shanghai \
    LANG=en_US.utf8 \
    LC_ALL=en_US.utf8 \
    PATH="/opt/venv/bin:${PATH}"

# 安装运行时依赖（去掉 python3-pip 和 python3.10-dev，虚拟环境自带）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
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
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 创建应用目录
RUN mkdir -p /data/spug /var/log/supervisor

# 设置工作目录
WORKDIR /data/spug

# 从前端构建阶段复制构建产物
COPY --from=frontend-builder /app/build ./spug_web/build

# 从后端构建阶段复制代码
COPY --from=backend-builder /app ./spug_api

# 从后端构建阶段复制虚拟环境（包含所有 Python 包和命令，无路径硬编码、不覆盖系统 bin）
COPY --from=backend-builder /opt/venv /opt/venv

# 复制配置文件
COPY docker/config/nginx.conf /etc/nginx/nginx.conf
COPY docker/config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/config/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 暴露端口
EXPOSE 80

# 启动命令
ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
