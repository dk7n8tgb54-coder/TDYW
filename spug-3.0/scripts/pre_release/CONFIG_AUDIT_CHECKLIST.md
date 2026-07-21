# Spug 发布前配置审计手册（阶段 1）

> 目标：在代码部署到生产前，系统性地检查"开发环境正常但生产可能炸"的配置差异问题。

## 一、自动化审计（一键执行）

### 运行方式

```powershell
# 通过 stdin 注入容器执行（不污染容器文件系统，推荐）
wsl bash -c "docker exec -i tdyw python - < scripts/pre_release/audit_config.py"
```

### 自动检查覆盖范围（11 大类）

| 类别 | 检查项 |
|---|---|
| 1. Django 安全配置 | DEBUG / SECRET_KEY / ALLOWED_HOSTS / ALLOWED_ORIGINS / USE_TZ / TIME_ZONE / Celery 时区 |
| 2. 数据库 | NAME/USER / CONN_MAX_AGE / 连通性 / MySQL 版本 / max_connections / innodb_buffer_pool / sql_mode / slow_query_log |
| 3. Redis | DB0(channels) / DB1(cache) / DB2(broker) / DB3(result) / 权限缓存键数量 |
| 4. Celery | Worker ping / Beat schedule 数量与任务清单 |
| 5. 文件系统 | MEDIA_ROOT / STATIC_ROOT / TRANSFER_DIR / logs / storage/documents / storage/document_chunks |
| 6. 数据库迁移 | 未应用迁移 / 模型-迁移一致性 (makemigrations --check) |
| 7. 业务模块 | 19 个业务 app 是否全部在 INSTALLED_APPS |
| 8. 关键文件 | nginx.conf / SSL 证书 / supervisord.conf / 11 个 start-*.sh / build/index.html / SSL 有效期 |
| 9. Supervisor 进程 | 13 个预期进程是否全部 RUNNING |
| 10. 环境变量 | 11 个必需环境变量是否设置 |
| 11. Docker Volume | MEDIA_ROOT 可写性 / named volume 陷阱提醒 |

### 退出码

- `0` = 无 FAIL（可有 WARN/INFO）
- `1` = 存在 FAIL，必须处理

---

## 二、手工审计项（无法自动化的部分）

### A. 代码冻结（部署前必做）

- [ ] `git status` 检查所有未提交变更
- [ ] 决定每个文件的 commit/discard（特别是 Dockerfile / docker-compose.yml / entrypoint.sh / settings.py）
- [ ] 确认新增的 migration 文件已 commit（如 `radio_license/migrations/0010_station_frequency_approval.py`）
- [ ] 确认新文件已 commit（如 `department_duty_log/pdf_export.py`、前端新组件）

### B. .env 文件实际值审查（不写入版本库，人工核对）

容器内 `.env` 应至少包含以下 key（**值需人工核对强度**）：

```env
# 必需（当前已有）
MYSQL_ROOT_PASSWORD=<强密码，至少 16 位>
MYSQL_PASSWORD=<强密码>
MYSQL_DATABASE=<数据库名>
DJANGO_SECRET_KEY=<至少 50 位随机字符，用 python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())" 生成>
DEBUG=False
ALLOWED_HOSTS=<具体域名或IP，不要用 *>

# 建议补充（当前缺失，使用 settings.py 默认值）
REDIS_PASSWORD=<Redis 密码，内网可空但建议设置>
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
ALLOWED_ORIGINS=https://<你的域名>
KKFILEVIEW_API_URL=/kkfileview
KKFILEVIEW_SERVER_URL=http://tdyw
TZ=Asia/Shanghai
```

**重点核查**：
- [ ] `DJANGO_SECRET_KEY` 不能是 `dev-only-insecure-key-do-not-use-in-production`
- [ ] `MYSQL_ROOT_PASSWORD` 不能是弱密码（如 `root`/`123456`）
- [ ] `DEBUG=False`
- [ ] `ALLOWED_HOSTS` 不要用 `*`（写具体域名/IP，逗号分隔）

### C. SSL 证书

- [ ] 证书文件 `docker/certs/prod/spug.crt` 和 `spug.key` 存在
- [ ] 证书未过期（自动脚本会显示到期时间）
- [ ] 证书 CN/SAN 与实际访问域名匹配
- [ ] 自签名 CA 证书 `docker/certs/ca/ca.crt` 可供用户下载安装

### D. Nginx 配置审查（已人工核查）

基于 `docker/config/nginx.conf` 的审查结论：

- [x] HTTP 80 端口：`/api/` 不跳转 HTTPS（kkFileView 回调/健康检查需要），其他请求跳转 HTTPS
- [x] HTTPS 443 端口：完整 SSL 配置 + 安全响应头（X-Frame-Options/CSP/HSTS/X-Content-Type-Options）
- [x] 上传 API 专用 upstream（9003 端口）隔离普通 API（9001）
- [x] WebSocket `/api/ws/` 代理到 9002
- [x] kkFileView `/kkfileview/` 代理 + sub_filter 替换硬编码 URL
- [x] `/media/` 直接服务 + 30 天缓存
- [x] SPA 路由 `try_files $uri $uri/ /index.html`
- [x] 速率限制（api_limit 100r/s, login_limit 5r/m）
- [x] Gzip 压缩
- [x] `server_tokens off` 隐藏版本号
- [ ] **注意**：无 `/static/` location——这是正常的，项目不用 Django admin，前端静态文件走 `spug_web/build/`

### E. Supervisor 配置审查（已人工核查）

基于 `docker/config/supervisord.conf` 的审查结论：

- [x] 13 个 program 全部配置（nginx/redis/spug-api/spug-api-upload/spug-ws/spug-worker/spug-celery/spug-celery-beat/spug-celery-cleanup/spug-celery-merge/spug-celery-batch/spug-celery-thumbnail/spug-celery-radio-license）
- [x] 全部 `autostart=true` + `autorestart=true`
- [x] priority 顺序合理（nginx 10 → redis 15 → api 20 → ws 25 → worker 30 → celery 35+ → beat 50）
- [x] `minfds=65535` + `minprocs=65535`
- [x] Celery worker 按队列拆分（merge/cleanup/batch/thumbnail/radio_license 各自独立）

### F. MySQL 配置审查（已人工核查）

基于 `docker/config/mysqlnew.cnf` 的审查结论：

- [x] `character-set-server=utf8mb4` + `collation-server=utf8mb4_unicode_ci`
- [x] `max_connections=300`（8G 服务器适配）
- [x] `innodb_buffer_pool_size=2G`（8G 服务器适配）
- [x] `innodb_flush_log_at_trx_commit=2`（性能与安全平衡）
- [x] `slow_query_log=1` + `long_query_time=1`
- [x] `sql_mode` 包含 STRICT_TRANS_TABLES
- [x] `max_allowed_packet=256M`（与 Django OPTIONS 匹配）
- [x] binlog 启用 + 保留 7 天

### G. Docker Volume 陷阱（关键！历史血泪教训）

**问题**：`docker-compose.yml` 中 `tdyw-media` / `tdyw-documents` / `tdyw-document-chunks` 是 named volume，会遮盖 spug_api 的 bind mount 子目录。

- [ ] **确认数据持久化策略**：named volume 的数据**独立于宿主机文件系统**，切换 compose 项目名（dev/docker）或 `docker volume rm` 即丢失
- [ ] **生产部署前**：决定是否改为 bind mount（如 `./data/media:/data/spug/spug_api/media`）
- [ ] **备份策略**：如果保留 named volume，必须有 `docker volume` 级别的备份机制
- [ ] **历史教训**：曾导致签名文件全部丢失（见项目 MEMORY）

### H. 数据备份与恢复预案

- [ ] **数据库备份**：`database_maintenance/` 下的脚本能在生产服务器跑通
- [ ] **文件备份**：media / storage/documents 的备份周期与数据库一致
- [ ] **恢复演练**：用备份恢复到一个新容器，确认数据完整
- [ ] **恢复顺序**：停业务 → 恢复 DB → 清空 documents → 恢复文件 → 启动 → 检查
- [ ] **回滚预案文档**：写一份"出问题怎么回滚"的 runbook

### I. Django check --deploy 警告处理

自动脚本会跑 `manage.py check --deploy`，预期警告（API 项目可接受）：
- `security.W002` XFrameOptionsMiddleware 缺失 → **nginx 已配置 X-Frame-Options，可忽略**
- `security.W003` CsrfViewMiddleware 缺失 → **API 用 token 鉴权非 session，可忽略**
- `security.W004` SECURE_HSTS_SECONDS 未设置 → **nginx 已配置 HSTS，可忽略**
- `security.W008` SECURE_SSL_REDIRECT 未设置 → **nginx 已配置 HTTP→HTTPS 跳转，可忽略**
- `security.W010` SESSION_COOKIE_SECURE 未设置 → **API 不用 session cookie，可忽略**
- `fields.W342` DocumentSystemFolder.folder unique=True → **已知设计，可忽略**

### J. 镜像构建与部署演练

- [ ] **fresh 镜像构建**：`docker build -t tdyw:test -f docker/Dockerfile .` 能成功
- [ ] **容器拉起**：`docker-compose up -d` 三个容器全部 healthy
- [ ] **healthcheck 通过**：`curl https://localhost/api/document/health/` 返回 200
- [ ] **首屏加载**：浏览器访问 `https://localhost` 能看到登录页
- [ ] **登录测试**：admin / Admin888.. 能登录（首次启动 entrypoint.sh 会创建）

---

## 三、审计结果判定标准

| 等级 | 含义 | 处理方式 |
|---|---|---|
| PASS | 通过 | 无需处理 |
| WARN | 警告 | 评估后决定是否处理，可上线 |
| FAIL | 失败 | **必须处理**，否则不可上线 |
| INFO | 信息 | 仅供参考，无需处理 |

## 四、完成发布前测试的下一步

阶段 1 完成后，按优先级继续：
- **阶段 2**：fresh 库全量迁移演练
- **阶段 3**：已有 5 个 app 后端测试 + 17 个前端 jest 测试全跑
- **阶段 4**：17 个无测试 app 的手工冒烟清单
- **阶段 5**：跨模块集成测试
- **阶段 6**：locust 压测
- **阶段 7**：部署/回滚演练
