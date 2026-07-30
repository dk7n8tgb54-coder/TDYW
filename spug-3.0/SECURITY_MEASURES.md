# 平台安全措施汇总

> 更新日期：2026-07-30
> 验证脚本：`spug_api/apps/security_audit_prod.py`（短板检测）+ `spug_api/apps/security_fix_verify.py`（修复验证，19/19 PASS）

---

## 第一部分：内网安全现状（已完成）

### 一、认证与授权

| 措施 | 实现位置 | 说明 |
|---|---|---|
| Token 认证 | `libs/middleware.py` | 32 字符 access_token，Redis 存储，TTL 过期 |
| RBAC 权限体系 | `page_perms` + Redis 缓存 | 按页面+操作码控制，`is_supper` 放行 |
| 登录暴力破解防护 | `account/views.py` | Redis 记录失败次数，5 次锁定 30 分钟 |
| 多租户隔离 | `libs/tenant_middleware.py` | `TenantManager` 自动过滤 `tenant_id` |
| CSRF 防护 | `libs/csrf_protection.py` | Origin/Referer 校验 |
| 密码复杂度策略 | `account/utils.py:verify_password()` | 长度≥8 + 数字 + 小写 + 大写 + 特殊字符，创建/修改/重置密码时强制校验 |

### 二、数据库安全

| 措施 | 实现位置 | 说明 |
|---|---|---|
| ORM 全覆盖 | 全项目 | 参数化查询，防 SQL 注入 |
| 事务保护 | `settings.py:ATOMIC_REQUESTS=True` | 每个请求自动事务 |
| 逻辑删除 | `is_deleted` + `deleted_at` | 核心业务表不物理删除 |
| 幂等性设计 | `libs/idempotency.py` | 时间窗口去重，8 个 POST 端点已接入 |
| 最小权限账号 | `docker/.env: MYSQL_USER=tdyw` | 非 root 账号，仅 DML+DDL 权限 |
| 数据库端口隔离 | `docker-compose.yml` | `127.0.0.1:3306:3306`，仅本地可访问 |
| 账号自动创建 | `docker-compose.yml` tdyw-db 服务 | `MYSQL_USER` + `MYSQL_PASSWORD` 环境变量，全新部署自动创建 |
| 账号迁移脚本 | `docker/scripts/init_tdyw_account.sql` | 已有数据库一次性迁移用 |

### 三、Redis 安全

| 措施 | 实现位置 | 说明 |
|---|---|---|
| Redis 密码 | `docker/.env: REDIS_PASSWORD` | 强密码，通过环境变量自动传递 |
| 条件启动 | `docker/config/supervisord.conf` | `bash -c` 条件设置 `--requirepass`，有密码则启用，无则兼容开发环境 |
| 端口不暴露 | `docker-compose.yml` | Redis 端口不映射到宿主机，仅容器内 127.0.0.1 可访问 |

### 四、文件上传安全

| 措施 | 实现位置 | 说明 |
|---|---|---|
| 路径遍历防护 | `document_utils.py:is_safe_path()` | `os.path.realpath` 比对基目录 |
| 文件名校验 | `view_utils.py:validate_file_name()` | 禁止 `..`、`/`、`\`、`:`、`*`、`?`、`"`、`<`、`>`、`|` |
| 分片 MD5 校验 | `chunkUpload.js` + `merge.py` | 上传完整性验证 |
| 合并幂等性 | `merge.py:check_idempotency()` | 防重复合并 |
| evidence 模块白名单 | `evidence/attachment_service.py` | 附件模块有扩展名白名单 |

### 五、网络与传输安全

| 措施 | 实现位置 | 说明 |
|---|---|---|
| HTTPS/TLS | `docker/config/nginx.conf` | TLSv1.2/1.3，SSL 证书挂载 |
| HTTP->HTTPS 重定向 | `nginx.conf` | 80 端口自动 301 到 443 |
| HSTS | `nginx.conf` | `Strict-Transport-Security: max-age=31536000` |
| CSP | `nginx.conf` | 完整 Content-Security-Policy |
| X-Frame-Options | `nginx.conf` | `SAMEORIGIN` 防点击劫持 |
| X-Content-Type-Options | `nginx.conf` | `nosniff` 防 MIME 嗅探 |
| X-XSS-Protection | `nginx.conf` | `1; mode=block` |
| Referrer-Policy | `nginx.conf` | `strict-origin-when-cross-origin` |
| Permissions-Policy | `nginx.conf` | camera/microphone/geolocation/payment 禁用 |
| X-Download-Options | `nginx.conf` | `noopen` |
| server_tokens off | `nginx.conf` | 隐藏 Nginx 版本号 |

### 六、Cookie 安全

| 措施 | 实现位置 | 说明 |
|---|---|---|
| SESSION_COOKIE_SECURE | `settings.py` | `DEBUG=False` 时自动启用，Cookie 仅通过 HTTPS 传输 |
| CSRF_COOKIE_SECURE | `settings.py` | `DEBUG=False` 时自动启用 |
| SESSION_COOKIE_SAMESITE | Django 4.2 默认 | 默认值 `'Lax'`，防 CSRF |

### 七、API 限流

| 措施 | 实现位置 | 说明 |
|---|---|---|
| 通用 API 限流 | `nginx.conf: /api/ location` | `limit_req zone=api_limit burst=20 nodelay`（100r/s，HTTP+HTTPS 双 server） |
| 登录接口限流 | `nginx.conf: /api/account/login/ location` | `limit_req zone=login_limit burst=5 nodelay`（5r/m，独立 location 块） |
| 登录暴力防护 | `account/views.py` | Redis 失败计数，5 次锁定 30 分钟（应用层） |

### 八、审计与可追溯

| 措施 | 实现位置 | 说明 |
|---|---|---|
| 全请求审计日志 | `logs/middleware.py` | 记录请求/响应，含请求人、时间、参数 |
| 哈希链防篡改 | `logs/hash_chain.py` | SHA256 + `prev_hash` 链式校验 |
| 业务审计事件 | `logs/audit.py:record_audit_event()` | 增删改操作留痕 |
| 审计日志查询限制 | 90 天 + 1000 条 | 防无边界查询 |

### 九、Django 安全配置

| 措施 | 实现位置 | 说明 |
|---|---|---|
| DEBUG=False | `docker/.env` | 生产环境关闭调试 |
| ALLOWED_HOSTS | `docker/.env` | 非通配符，限定具体 IP/域名 |
| ALLOWED_ORIGINS | `docker/.env` | Origin/Referer 校验白名单 |
| DJANGO_SECRET_KEY | `docker/.env` | 随机密钥，非硬编码 |
| Celery JSON 序列化 | `settings.py` | 禁用 pickle，仅 JSON |

### 十、基础设施安全

| 措施 | 实现位置 | 说明 |
|---|---|---|
| Docker 容器隔离 | `docker-compose.yml` | 服务运行在 `tdyw-network` 桥接网络 |
| Nginx 反向代理 | `docker-compose.yml` | 端口转发，隐藏后端服务 |
| nginx.conf 只读挂载 | `docker-compose.yml` | `:ro` 防止容器内篡改 |
| SSL 证书挂载 | `docker-compose.yml` | `./certs/prod:/etc/nginx/ssl:ro` |
| 容器资源限制 | `docker-compose.yml` | tdyw 2G / tdyw-db 3G / kkfileview 1.5G |
| 健康检查 | `docker-compose.yml` | 所有服务配置 healthcheck |
| 自动重启 | `docker-compose.yml` | `restart: unless-stopped` |
| kkFileView 禁止上传 | `docker-compose.yml` | `KK_FILE_UPLOAD_ENABLED=false` |

### 十一、输入验证与注入防护

| 措施 | 实现位置 | 说明 |
|---|---|---|
| ORM 全覆盖 | 全项目 | 参数化查询，防 SQL 注入 |
| 表单校验 | 各 views.py | JSON body 参数类型+必填校验 |
| 幂等性去重 | `libs/idempotency.py` | 8 个 POST 端点接入 |
| 批量删除安全 | 各 services.py | 分批 + failed_ids 排除 + max_iterations |

### 十二、已修复的内网短板（2026-07-30）

| 短板 | 修复方式 | 验证 |
|---|---|---|
| Redis 默认无密码 | `.env` 添加 `REDIS_PASSWORD`，`supervisord.conf` 条件设置 `--requirepass`，`docker-compose.yml` 传递环境变量 | ✅ |
| MYSQL_USER=root | `.env` 改为 `tdyw`，`docker-compose.yml` 改为 `${MYSQL_USER:-tdyw}`，`tdyw-db` 添加 `MYSQL_USER`+`MYSQL_PASSWORD` 自动创建 | ✅ |
| SESSION_COOKIE_SECURE 未设 | `settings.py` 添加 `if not DEBUG: SESSION_COOKIE_SECURE = True` | ✅ |
| CSRF_COOKIE_SECURE 未设 | `settings.py` 添加 `if not DEBUG: CSRF_COOKIE_SECURE = True` | ✅ |
| Nginx limit_req 未应用 | `nginx.conf` 添加 `limit_req zone=api_limit`（HTTP+HTTPS）+ `limit_req zone=login_limit`（登录接口） | ✅ |

### 十三、已知待改进项（内网可接受）

| 项目 | 说明 | 优先级 |
|---|---|---|
| document 模块无文件类型白名单 | `validate_file_name()` 不检查扩展名，可上传 .py/.sh/.html | P2（暂不修复） |
| 无闲置会话超时 | TOKEN_TTL=8h 固定过期，但有滑动过期（活动刷新 TTL） | P3（可接受） |
| 数据库密码无特殊字符 | `Dt6299093`（9位，有数字+大写，无特殊字符） | P3（用户指定） |
| 密码明文存储 | `.env` 文件明文，未使用 `_FILE` 方式 | P3（内网可接受） |

---

## 第二部分：外网部署需要新增的措施

> 以下措施在内网环境下非必需，但**部署到外网前必须完成**。
> 按优先级分为 P0（上线前必须）、P1（上线后尽快）、P2（持续加固）。

### P0：上线前必须完成（不完成不可上线）

#### 1. 验证码（CAPTCHA）

- **现状**：登录无验证码，仅靠 Redis 失败计数 + Nginx 限流（5r/m）
- **外网风险**：自动化攻击可绕过 IP 限流（多 IP 轮换），对账号进行分布式暴力破解
- **需要做的**：登录失败 3 次后要求图形验证码或滑动验证；可集成 hCaptcha/Tencent Captcha
- **实现位置**：前端 `spug_web/src/pages/login` + 后端 `account/views.py`

#### 2. document 模块文件类型白名单

- **现状**：`validate_file_name()` 不检查扩展名，可上传 .py/.sh/.html/.php
- **外网风险**：上传恶意脚本，若服务端有解析漏洞可导致 RCE（远程代码执行）
- **需要做的**：`validate_file_name()` 增加扩展名白名单（参考 evidence 模块的 `allowed_extensions`）；同时校验 MIME 类型 + 文件头 magic number
- **实现位置**：`document/libs/view_utils.py`

#### 3. 文件存储隔离

- **现状**：上传文件存在容器内 `/data/spug/media/`，通过 Nginx `/media/` 直接可访问
- **外网风险**：上传的 .html 文件可被直接访问执行 XSS；上传的恶意文件可被直接下载
- **需要做的**：
  - Nginx `/media/` location 添加 `Content-Disposition: attachment` 强制下载（不在线渲染）
  - 或将文件存储迁移到 OSS/MinIO 等独立对象存储
  - 文件目录禁止执行权限（`chmod -x`）
- **实现位置**：`docker/config/nginx.conf` + `settings.py:MEDIA_ROOT`

#### 4. 2FA/MFA 双因素认证

- **现状**：仅账号密码登录
- **外网风险**：密码泄露即账号沦陷
- **需要做的**：关键账号（管理员）强制 TOTP 双因素认证；可集成 `django-otp` 或 `pyotp`
- **实现位置**：新增 `apps/account/two_factor.py` + 前端登录流程

#### 5. 实时监控与告警

- **现状**：有审计日志，但无实时告警机制
- **外网风险**：攻击发生但无法及时发现
- **需要做的**：
  - 异常登录告警：短时间内多 IP 登录、异地登录、非工作时间登录
  - 错误率突增告警：5xx 错误率、登录失败率
  - 集成 `libs/alert.py:send_alert()` 实现告警推送（邮件/钉钉/企业微信）
- **实现位置**：扩展 `logs/middleware.py` + 新增告警规则

#### 6. 定期漏洞扫描

- **现状**：无漏洞扫描机制
- **外网风险**：依赖组件存在已知 CVE 漏洞未修复
- **需要做的**：
  - `pip-audit` 或 `safety check` 定期扫描 Python 依赖
  - `npm audit` 扫描前端依赖
  - 定期更新基础镜像（`tdyw:0720` -> 更新版本）
  - 建议每月一次，发现高危漏洞 48 小时内修复

### P1：上线后尽快完成

#### 7. WAF（Web 应用防火墙）

- **现状**：Nginx 仅有限流，无 WAF 规则
- **外网风险**：SQL 注入、XSS、CC 攻击无应用层过滤
- **需要做的**：部署 ModSecurity + OWASP CRS 规则集，或使用云 WAF（阿里云/腾讯云 WAF）
- **实现位置**：Nginx 加载 ModSecurity 模块，或 DNS 接入云 WAF

#### 8. DDoS 防护

- **现状**：无 DDoS 防护，单机带宽有限
- **外网风险**：流量打满导致服务不可用
- **需要做的**：接入云 DDoS 防护（阿里云 DDoS 高防 / 腾讯云大禹），或使用 CDN 前置（Cloudflare/阿里云 CDN）
- **实现位置**：DNS 层配置，不涉及代码改动

#### 9. 登录异常通知

- **现状**：无登录通知机制
- **外网风险**：账号被盗用用户无感知
- **需要做的**：异常登录（新 IP / 新设备 / 非工作时间）发送通知（邮件/短信/企业微信）
- **实现位置**：扩展 `account/views.py:handle_user_info()` + `libs/alert.py`

#### 10. 密码历史

- **现状**：改密码时不检查历史密码
- **外网风险**：用户改回旧密码，旧密码可能已泄露
- **需要做的**：记录最近 5 次密码哈希，改密码时禁止重复
- **实现位置**：新增 `account/models.py:PasswordHistory` 模型

#### 11. 按用户限流

- **现状**：Nginx 限流按 IP（`$binary_remote_addr`），应用层按 IP+账号
- **外网风险**：多 IP 轮换可绕过 IP 限流
- **需要做的**：登录后 API 限流改为按用户 ID（`limit_req_zone $http_x_user_id`），或应用层中间件实现
- **实现位置**：`nginx.conf` + `libs/middleware.py`

#### 12. HTTPS 证书自动续期

- **现状**：SSL 证书手动挂载，无自动续期
- **外网风险**：证书过期导致服务不可用或浏览器报警
- **需要做的**：使用 Let's Encrypt 免费证书 + certbot 自动续期，或云 SSL 证书托管
- **实现位置**：`docker/scripts/renew_cert.sh` + crontab

### P2：持续加固

#### 13. SECRET_KEY 轮换

- **现状**：`DJANGO_SECRET_KEY` 写在 `.env` 中，从不轮换
- **外网风险**：密钥泄露后可伪造 session/token
- **需要做的**：使用 KMS/Vault 管理密钥，定期轮换（每季度）；轮换时需 invalidate 所有 session
- **实现位置**：`settings.py` + KMS 集成

#### 14. 备份加密

- **现状**：`backups/` 目录有备份脚本，但备份文件未加密
- **外网风险**：备份文件泄露导致数据泄露
- **需要做的**：备份时用 GPG/openssl 加密，密钥单独管理
- **实现位置**：`backups/backup_set_create.sh` 加 `openssl enc` 步骤

#### 15. API 版本化

- **现状**：API 无版本前缀
- **外网风险**：发现漏洞后无法平滑废弃旧版本 API
- **需要做的**：URL 加版本前缀 `/api/v1/`，或 Header `Accept-Version`
- **实现位置**：`spug/urls.py` + 前端 API 调用

#### 16. 数据库只读副本

- **现状**：所有读写走主库
- **外网风险**：报表/导出大量查询影响主库性能和安全性
- **需要做的**：搭建只读副本，报表/导出走只读副本
- **实现位置**：`settings.py` 配置多数据库路由

#### 17. 安全响应头补充

- **现状**：已有 7 个安全头
- **可补充**：`Cross-Origin-Embedder-Policy: require-corp` + `Cross-Origin-Opener-Policy: same-origin`
- **实现位置**：`docker/config/nginx.conf`

---

## 第三部分：内外网对照表

| 安全维度 | 内网现状 | 外网要求 | 差距 |
|---|---|---|---|
| HTTPS/TLS | ✅ 已有 | ✅ 需要 | 无差距 |
| 安全响应头 | ✅ 7 个 | ✅ +2 个 | 补充 COEP/COOP |
| 密码策略 | ✅ 复杂度校验 | ✅ + 密码历史 | 补充密码历史 |
| 登录防护 | ✅ 限流+暴力锁定 | ✅ + 验证码+2FA | 补充验证码+2FA |
| API 限流 | ✅ Nginx 按 IP | ✅ + 按用户 | 补充按用户限流 |
| CSRF 防护 | ✅ Origin+Cookie | ✅ 需要 | 无差距 |
| SQL 注入防护 | ✅ ORM 全覆盖 | ✅ 需要 | 无差距 |
| 文件上传安全 | ⚠️ 路径遍历已防 | ✅ + 白名单+存储隔离 | 补充白名单+隔离 |
| Redis 安全 | ✅ 密码+不暴露 | ✅ 需要 | 无差距 |
| 数据库安全 | ✅ 最小权限+端口隔离 | ✅ 需要 | 无差距 |
| 审计日志 | ✅ 哈希链 | ✅ + 实时告警 | 补充告警 |
| WAF/DDoS | ❌ 无 | ✅ 必须 | 新增 WAF+DDoS |
| 监控告警 | ❌ 有日志无告警 | ✅ 必须 | 新增告警 |
| 漏洞扫描 | ❌ 无 | ✅ 必须 | 新增定期扫描 |
| 证书续期 | ❌ 手动 | ✅ 自动 | 新增 certbot |
| 备份加密 | ❌ 未加密 | ✅ 加密 | 新增加密 |
