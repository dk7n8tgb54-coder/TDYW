# SSL/HTTPS 配置经验总结

## 核心概念

### SSL 证书的作用
1. **加密传输**：防止数据在传输过程中被窃听（最主要的作用）
2. **身份验证**：确认服务器身份（内网意义不大，防止钓鱼）

### 证书类型
- **自签名证书**：自己签自己，浏览器显示"不安全"
- **CA 签名证书**：由证书机构签名，浏览器安装 CA 后信任

### CA（证书机构）的作用
- 类似"公安局"，颁发"身份证"（证书）
- 浏览器信任 CA，就信任所有 CA 签名的证书
- 私有 CA：自己创建的证书机构，用于内网

## 关键文件

| 文件 | 作用 | 部署位置 | 是否机密 |
|------|------|----------|----------|
| `ca.key` | CA 私钥 | 服务器 | ✅ 机密 |
| `ca.crt` | CA 根证书 | 客户端（安装） | ❌ 公开 |
| `spug.key` | 服务器私钥 | 服务器 | ✅ 机密 |
| `spug.crt` | 服务器证书 | 服务器 | ❌ 公开 |

### 证书生成流程
```
1. 生成 CA 私钥
2. 生成 CA 证书（自签名）
3. 生成服务器私钥
4. 创建证书签名请求（CSR）
5. 用 CA 签名服务器证书
6. 删除临时文件（CSR）
```

## 开发 vs 生产环境

### 开发环境
- 证书位置：`certs/dev/`
- 域名：`localhost`
- 访问方式：`https://localhost`
- Nginx 配置：`config/dev/nginx.conf`

### 生产环境
- 证书位置：`certs/prod/`
- 域名：`spug.internal` + 实际 IP
- 访问方式：`https://实际IP` 或 `https://spug.internal`
- Nginx 配置：`config/prod/nginx.conf`

## 关键配置点

### 1. Docker Compose 证书映射
```yaml
volumes:
  - ./certs/dev:/etc/nginx/certs      # 开发环境
  - ./certs/prod:/etc/nginx/certs     # 生产环境
  - ./config/dev/nginx.conf:/etc/nginx/nginx.conf:ro
```

### 2. Nginx HTTPS 配置
```nginx
server {
    listen 443 ssl http2;
    ssl_certificate /etc/nginx/certs/spug.crt;
    ssl_certificate_key /etc/nginx/certs/spug.key;
}

# HTTP 强制跳转 HTTPS
server {
    listen 80;
    return 301 https://$server_name$request_uri;
}
```

### 3. 证书 SAN（Subject Alternative Name）配置
```
[alt_names]
DNS.1 = localhost
DNS.2 = spug.internal
IP.1 = 127.0.0.1
IP.2 = 192.168.1.100  # 实际 IP
```

## 常见问题

### Q1: 为什么访问 `http://127.0.0.1` 会跳转到 `https://localhost`？
**原因：** Nginx 配置的 `$server_name` 是 `localhost`，重定向时使用这个名称。

**解决方法：**
- 直接访问 `https://127.0.0.1`（跳过 HTTP 重定向）
- 或者修改配置使用 `$host` 替代 `$server_name`

### Q2: 为什么修改脚本后还需要重新生成证书？
**原因：**
- 修改脚本 ≠ 修改证书
- 需要重新运行脚本生成新证书
- 重启 Docker 容器加载新证书

**流程：**
1. 修改脚本（`setup-ca.sh` 或 `setup-dev-ca.ps1`）
2. 运行脚本生成新证书
3. 重启 Docker：`docker-compose restart`

### Q3: 客户端应该安装 `ca.crt` 还是 `spug.crt`？
**答案：** 只能安装 `ca.crt`！

**原因：**
- `ca.crt` 是根证书，浏览器信任后自动信任所有 CA 签名的证书
- `spug.crt` 是服务器证书，不能作为信任根

### Q4: HTTP 可以删除吗？
**答案：** 不可以！

**原因：**
- HTTP 是入口，用户可能输入 `http://...`
- 自动跳转到 HTTPS，提升用户体验
- 符合安全最佳实践

### Q5: `server_name` 和证书里的域名有什么区别？
- `server_name`：Nginx 虚拟主机匹配，不影响证书验证
- 证书里的域名：浏览器验证时使用
- 访问 IP 地址时，证书包含该 IP 即可

## 部署流程

### 生产环境 HTTPS 配置步骤
1. 在 Linux 服务器上创建目录：
   ```bash
   mkdir -p /opt/spug-3.0/certs/prod
   mkdir -p /opt/spug-3.0/certs/ca
   mkdir -p /opt/spug-3.0/config/prod
   ```

2. 通过 U 盘复制文件到服务器：
   - `setup-ca.sh`
   - `ca/ca.crt`, `ca/ca.key`, `ca/ca.srl`
   - `config/prod/nginx.conf`

3. 修改 `setup-ca.sh` 中的默认 IP（持久化）：
   ```bash
   vi setup-ca.sh
   # 修改第 18 行
   IP_ADDR=${2:-"192.168.1.100"}
   # 改成实际 IP
   ```

4. 运行脚本生成服务器证书：
   ```bash
   cd /opt/spug-3.0/certs
   ./setup-ca.sh spug.internal <实际IP>
   ```

5. 分发 CA 证书给客户端：
   - 从 Windows 开发电脑的 `client-dist/` 文件夹复制
   - 客户端运行 `install-ca.bat`（管理员身份）

6. 重启 Docker：
   ```bash
   cd /opt/spug-3.0
   docker-compose -f docker-compose.prod.yml restart
   ```

7. 验证：
   - 访问 `https://实际IP`
   - 应该看到绿色🔒图标

## 安全注意事项

### 1. 私钥保护
- 设置严格权限：`chmod 600 *.key`
- 只允许 root 用户读取
- 定期检查文件访问日志

### 2. 密钥泄露的后果
- 可以冒充服务器（中间人攻击）
- 可以解密新的连接（如果有网络控制）
- 无法解密历史通信（完美前向保密）

### 3. 防护措施
- 防止服务器被攻破（更新系统、强密码、限制 SSH）
- 定期轮换证书和密钥
- 配置 IP 白名单、防火墙

### 4. 内网环境风险
- 攻击者难以发起中间人攻击
- 主要是防止局域网内的网络嗅探

## 经验教训

### 1. 修改脚本 ≠ 修改证书
- **错误：** 修改 `setup-ca.sh` 的 IP 后，以为证书已更新
- **正确：** 修改脚本后必须重新运行，生成新证书
- **验证：** 用 OpenSSL 查看证书内容确认

### 2. `client-dist` 脚本找不到文件
- **原因：** 双击 `.bat` 文件时，工作目录可能不是脚本所在目录
- **解决：** 添加 `cd /d "%~dp0"` 自动切换到脚本目录

### 3. 混淆证书类型
- **错误：** 客户端安装 `spug.crt`
- **正确：** 客户端只能安装 `ca.crt`
- **记忆：** CA 证书 = 根证书，安装在客户端

### 4. 忘记重启容器
- **原因：** 修改证书或配置后，容器仍加载旧文件
- **解决：** 每次修改后 `docker-compose restart`

### 5. IP 地址理解错误
- **错误：** 可以把证书 IP 改成任意 IP（如 8.8.8.8）
- **正确：** 只能改成实际属于本机的 IP 或局域网内有效的 IP

## 最佳实践

### 1. 使用域名而非 IP
- 配置 DNS 让 `spug.internal` 解析到实际 IP
- IP 变了只需改 DNS，不用重新生成证书
- 用户访问统一域名

### 2. 统一 CA 管理
- 开发和生产环境使用同一个 CA
- 客户端只需安装一次 CA 证书
- 简化客户端部署

### 3. 自动化部署
- 使用 `install-ca.bat` 批量安装
- 通过组策略或配置管理工具分发
- 减少人工操作错误

### 4. 证书生命周期管理
- 设置合理的有效期（10 年）
- 定期检查证书过期时间
- 提前规划证书更新

### 5. 备份策略
- 备份 `ca.key` 和 `ca.crt`（丢失需重新分发）
- 备份 `spug.key` 和 `spug.crt`（可重新生成）
- 定期备份 Docker Volumes

## 调试技巧

### 1. 查看证书内容
```bash
openssl x509 -in cert.crt -noout -text
```

### 2. 验证证书链
```bash
openssl verify -CAfile ca.crt spug.crt
```

### 3. 测试 HTTPS 连接
```bash
openssl s_client -connect localhost:443
```

### 4. 查看 Nginx 错误日志
```bash
docker-compose logs -f spug
docker exec spug cat /var/log/nginx/error.log
```

### 5. 检查证书是否正确加载
```bash
# 在容器内
docker exec spug ls -la /etc/nginx/certs/
docker exec spug cat /etc/nginx/nginx.conf | grep ssl_certificate
```

## IP 白名单配置

### 配置方式

**Nginx 层 IP 白名单（推荐）**

在 Nginx 配置文件中添加 `allow` 和 `deny` 指令：

```nginx
server {
    listen 443 ssl http2;
    server_name localhost;

    # IP 白名单配置
    allow 127.0.0.1;              # 本地访问
    allow 192.168.1.0/24;         # 允许 192.168.1.x 网段
    allow 10.0.0.0/8;             # 允许 10.x.x.x 网段
    deny all;                     # 拒绝其他所有 IP
}
```

**开发环境 vs 生产环境：**

| 环境 | 配置 | 说明 |
|------|------|------|
| 开发环境 | `# allow 127.0.0.1;` (注释掉) | 允许所有 IP 便于测试 |
| 生产环境 | `deny all;` (启用白名单) | 只允许指定 IP 访问 |

### 配置步骤

**1. 修改 Nginx 配置文件**
- 开发环境：`config/dev/nginx.conf`
- 生产环境：`config/prod/nginx.conf`

**2. 配置白名单规则**
```nginx
# 格式：allow IP地址/子网掩码;

# 示例：
allow 127.0.0.1;           # 单个 IP
allow 192.168.1.100;       # 单个 IP
allow 192.168.1.0/24;      # 192.168.1.1 - 192.168.1.254
allow 10.0.0.0/8;          # 10.0.0.0 - 10.255.255.255
allow 172.16.0.0/12;       # 172.16.0.0 - 172.31.255.255
deny all;                  # 拒绝其他所有
```

**3. 重启 Docker 容器**
```bash
docker-compose restart
```

### 常见网段

| 网段 | 说明 | 适用场景 |
|------|------|----------|
| `192.168.1.0/24` | C 类私有网络 | 家庭/小型办公室 |
| `10.0.0.0/8` | A 类私有网络 | 大型企业内网 |
| `172.16.0.0/12` | B 类私有网络 | 中型企业内网 |
| `127.0.0.1` | 本地回环 | 服务器自身访问 |

### 测试白名单

**1. 允许的 IP 访问**
```bash
curl https://localhost
# 应该正常返回
```

**2. 拒绝的 IP 访问**
```bash
curl https://192.168.1.100
# 应该返回 403 Forbidden
```

**3. 查看 Nginx 日志**
```bash
docker-compose logs -f spug
# 查看 access.log 和 error.log
```

### 其他安全措施

**1. 防火墙层（Linux iptables）**
```bash
# 允许特定 IP
iptables -A INPUT -s 192.168.1.100 -j ACCEPT
iptables -A INPUT -s 192.168.1.0/24 -j ACCEPT
iptables -A INPUT -j DROP
```

**2. 应用层（Spug 系统配置）**
- 在 Django 中配置 `ALLOWED_HOSTS`
- 配置中间件限制 IP

**3. VMware/虚拟机防火墙**
- 配置虚拟网络适配器
- 限制网络访问范围

### 安全建议

1. **最小权限原则**：只开放必要的 IP 和端口
2. **定期审计**：检查白名单是否仍然合理
3. **日志监控**：监控拒绝访问的日志，发现异常
4. **多层防护**：防火墙 + Nginx + 应用层，提高安全性

### 故障排查

**问题 1：所有 IP 都无法访问**
- 检查 `deny all` 是否放在了 `allow` 前面
- 检查 IP 格式是否正确
- 查看错误日志

**问题 2：白名单配置不生效**
- 确认修改了正确的配置文件（dev/prod）
- 确认重启了 Docker 容器
- 确认 `allow` 规则的顺序（从具体到一般）

**问题 3：内网 IP 无法访问**
- 检查子网掩码是否正确
- 检查虚拟机网络配置
- 确认 Docker 网络模式

## 接口限流配置

### Nginx limit_req 原理

**限流参数：**
```nginx
limit_req_zone $key zone=name:size rate=rate;
limit_req zone=name burst=n nodelay;
```

| 参数 | 说明 | 示例 |
|------|------|------|
| `$key` | 限流标识（按 IP） | `$binary_remote_addr` |
| `zone=name:size` | 共享内存区域 | `api_limit:10m` (10MB) |
| `rate` | 每秒请求数 | `10r/s` (10 requests/second) |
| `burst` | 突发容量 | `20` (允许 20 个突发请求） |
| `nodelay` | 不延迟处理 | 超过直接拒绝 |

### 配置说明

**在 http 块中定义限流区域：**
```nginx
http {
    # 定义限流区域（共享内存 10MB）
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;
    limit_req_zone $binary_remote_addr zone=general_limit:10m rate=30r/s;

    # ... 其他配置
}
```

**在 location 块中应用限流规则：**
```nginx
location /api/ {
    # 应用限流：每秒 10 次，突发 20 个请求
    limit_req zone=api_limit burst=20 nodelay;

    # ... 其他配置
}

location = /api/accounts/login/ {
    # 登录接口更严格：每分钟 5 次，突发 3 个请求
    limit_req zone=login_limit burst=3 nodelay;

    # ... 其他配置
}
```

### 限流规则说明

| 接口类型 | 限流规则 | 速率 | 突发 | 说明 |
|---------|---------|------|------|------|
| API 通用接口 | `api_limit` | 10r/s | 20 | 防止 CC 攻击 |
| 登录接口 | `login_limit` | 5r/m | 3 | 防止暴力破解 |
| 普通请求 | `general_limit` | 30r/s | 100 | 防止过载 |

### rate 参数说明

| 单位 | 示例 | 实际意义 |
|------|------|----------|
| `r/s` | `10r/s` | 每秒 10 个请求 |
| `r/m` | `5r/m` | 每分钟 5 个请求 |
| `r/h` | `100r/h` | 每小时 100 个请求 |

### burst 参数说明

**作用：** 允许短时间内的突发请求

**示例：**
```nginx
limit_req zone=api_limit burst=20 nodelay;
```

**工作原理：**
- 正常速率：10r/s
- 突发容量：20 个请求
- 超过 20 个：直接拒绝（`nodelay`）

**对比（有无 nodelay）：**
- **有 nodelay**：超过 20 个立即拒绝
- **无 nodelay**：超过 20 个延迟处理

### 防护效果

**1. 防止 CC 攻击（Challenge Collapsar）**
- 限制单个 IP 的请求频率
- 防止恶意脚本刷接口

**2. 防止暴力破解**
- 登录接口严格限制：5 次/分钟
- 超过限制返回 503 错误

**3. 保护服务器资源**
- 防止单个 IP 占用过多资源
- 保证其他用户正常访问

### 测试限流

**测试 1：正常访问（不触发限流）**
```bash
# 每秒 1 个请求，正常
for i in {1..5}; do
  curl https://localhost/api/ &
  sleep 1
done
```

**测试 2：触发限流**
```bash
# 快速发送 30 个请求
for i in {1..30}; do
  curl https://localhost/api/
done
# 应该看到部分请求返回 503
```

**测试 3：登录限流**
```bash
# 发送 10 个登录请求
for i in {1..10}; do
  curl -X POST https://localhost/api/accounts/login/ -d "username=test&password=123"
done
# 应该看到 503 错误（超过 5r/m）
```

### 查看限流日志

```bash
# 查看 Nginx 错误日志
docker-compose logs -f spug | grep "limiting requests"

# 应该看到类似输出：
# 2026/02/15 10:30:00 [error] limiting requests, excess: 0.100 by zone "api_limit"
```

### 响应码说明

| 状态码 | 说明 | 原因 |
|--------|------|------|
| 200 | 成功 | 请求正常处理 |
| 429 | Too Many Requests | 触发限流（标准） |
| 503 | Service Unavailable | 触发限流（Nginx 默认） |

### 调整建议

**根据实际场景调整：**

| 场景 | rate 建议 | burst 建议 |
|------|----------|------------|
| 高流量 API | 30r/s | 50 |
| 登录接口 | 10r/m | 5 |
| 静态资源 | 100r/s | 200 |
| 低流量系统 | 5r/s | 10 |

### 监控告警

**建议监控限流情况：**

1. **日志分析**
   ```bash
   # 统计限流次数
   docker logs spug 2>&1 | grep "limiting" | wc -l
   ```

2. **配置告警**
   - 限流次数超阈值 → 发邮件告警
   - 可能遭受攻击

3. **定期检查**
   - 分析异常 IP（大量触发限流）
   - 更新 IP 白名单或黑名单

### 高级配置

**1. 按接口类型限流**
```nginx
# 登录接口严格限制
location = /api/accounts/login/ {
    limit_req zone=login_limit burst=3 nodelay;
}

# 文件上传接口宽松限制
location ~* /api/upload {
    limit_req zone=upload_limit burst=50 nodelay;
}
```

**2. 按用户限流（需要后端配合）**
```nginx
# 使用请求头中的用户 ID
limit_req_zone $http_x_user_id zone=user_limit:10m rate=100r/s;

location /api/ {
    limit_req zone=user_limit burst=200 nodelay;
}
```

**3. 白名单 IP 不限流**
```nginx
geo $limit_key {
    default $binary_remote_addr;
    127.0.0.1 "";
    192.168.1.0/24 "";
}

limit_req_zone $limit_key zone=api_limit:10m rate=10r/s;
```

### 故障排查

**问题 1：限流太严格，正常用户被拒绝**
- 检查 `rate` 和 `burst` 是否合理
- 使用监控分析实际请求频率
- 增加限流阈值

**问题 2：限流不生效**
- 确认 `limit_req_zone` 定义在 `http` 块
- 确认 `limit_req` 应用在正确的 `location`
- 检查配置语法：`nginx -t`

**问题 3：登录接口频繁限流**
- 增加 `login_limit` 的 `rate`（如 10r/m）
- 增加 `burst` 容量（如 5）
- 或对特定 IP 不限流

### 故障排查

## 总结

1. **SSL 的核心价值**：加密传输，防止数据窃听
2. **CA 的作用**：让浏览器信任我们的证书
3. **配置要点**：证书映射、端口映射、自动跳转、IP 白名单
4. **部署流程**：生成证书 → 配置白名单 → 分发 CA → 重启容器
5. **安全重点**：保护私钥、IP 白名单、防止服务器被攻破
6. **常见陷阱**：修改脚本需重新生成、客户端只能装 CA 证书、白名单顺序

## 相关文件

- `certs/setup-ca.ps1` - Windows 环境创建 CA 和生产证书
- `certs/setup-ca.sh` - Linux 环境创建 CA 和生产证书
- `certs/setup-dev-ca.ps1` - 生成开发环境证书
- `certs/client-dist/` - 客户端安装包
- `config/dev/nginx.conf` - 开发环境 Nginx 配置
- `config/prod/nginx.conf` - 生产环境 Nginx 配置
- `docker-compose.yml` - 开发环境 Docker 配置
- `docker-compose.prod.yml` - 生产环境 Docker 配置

## 升级单号唯一约束验证

### 问题描述
升级单号的唯一约束需要实现：同一个租户下升级单号不能相同，不同租户下的升级单号可以相同。

### 解决方案
在 Django 模型中使用 `unique_together` 约束：

```python
class UpgradeRecord(models.Model, ModelMixin):
    tenant_id = models.CharField(max_length=50, default='', help_text='租户标识')
    upgrade_no = models.CharField(max_length=50)
    # ... 其他字段

    class Meta:
        db_table = 'exec_upgrade_records'
        unique_together = [['tenant_id', 'upgrade_no']]  # 同一租户内升级单号唯一
```

### 验证方法
通过 Django shell 脚本验证：

1. **同一租户内重复单号** - 应抛出 `IntegrityError`
2. **不同租户相同单号** - 应成功创建

验证脚本：`tests/verify_upgrade_constraint.py`

### 执行验证
```bash
# 将验证脚本复制到容器
docker cp tests/verify_upgrade_constraint.py spug:/tmp/

# 在容器内执行
docker exec spug bash -c "cd /data/spug/spug_api && python3 manage.py shell < /tmp/verify_upgrade_constraint.py"
```

### 验证结果
```
租户1创建成功: UPG_TEST_001, 租户=test_tenant
✓ 同一租户内重复被阻止: IntegrityError
✓ 租户2创建成功: UPG_TEST_001, 租户=test_tenant2

总记录数: 2
  - 租户=test_tenant, 单号=UPG_TEST_001, 系统=系统A
  - 租户=test_tenant2, 单号=UPG_TEST_001, 系统=系统C

✓ 测试通过: 同一租户内单号唯一，不同租户可相同
```

### 数据库约束
```sql
UNIQUE KEY `upgrade_no` (`tenant_id`,`upgrade_no`)
```

### 测试说明
- `tests/test_exec_models.py` 中包含单元测试
- 使用 `test_upgrade_unique_constraint` 测试同一租户内重复
- 使用 `test_upgrade_no_can_be_same_across_tenants` 测试不同租户可相同

### 经验教训

1. **唯一约束需要多字段组合**
   - 单独对 `upgrade_no` 加 `unique=True` 会导致所有租户都不能使用相同单号
   - 使用 `unique_together` 组合 `tenant_id` 和 `upgrade_no` 实现租户隔离

2. **验证脚本位置**
   - 容器内代码通过 Docker 挂载卷映射到本地
   - 测试脚本应该放在本地，然后复制到容器执行

3. **数据库迁移**
   - `unique_together` 约束需要通过 Django 迁移创建
   - 现有数据如果有冲突，迁移会失败
   - 迁移文件位置：`spug_api/apps/exec/migrations/`

4. **测试数据完整性**
   - 测试中创建对象时必须指定所有必需字段（checklist, dependencies, issues）
   - 否则可能使用默认空字符串，导致唯一约束判断错误

### 相关文件
- `spug_api/apps/exec/models.py` - UpgradeRecord 模型定义（第 147 行）
- `tests/verify_upgrade_constraint.py` - 约束验证脚本
- `tests/test_exec_models.py` - 单元测试用例
- `tests/debug_test.py` - 调试脚本

---

## React 性能优化经验

### 问题描述
`spug_web/src/pages/document/index.js` 中的 `handleSearch` 和 `handleSearchChange` 函数在每次渲染时都会重新创建，导致 Explorer.js 组件接收新的函数引用，触发不必要的重渲染。

### 优化方案
使用 React `useCallback` hook 缓存函数引用，避免每次渲染创建新函数：

```javascript
// 处理搜索 - 使用 useCallback 优化性能
const handleSearch = React.useCallback((value) => {
  setSearchText(value);
  if (explorerRef.current?.handleSearch) {
    explorerRef.current.handleSearch(value);
  }
}, []);

// 处理搜索框输入变化事件
const handleSearchChange = React.useCallback((e) => {
  const value = e.target.value;
  setSearchText(value);
  if (explorerRef.current?.handleSearch) {
    explorerRef.current.handleSearch(value);
  }
}, []);
```

### ESLint no-unused-expressions 问题修复

**问题描述：**
```javascript
explorerRef.current?.handleSearch?.(value);  // ESLint: no-unused-expressions
```

**原因：** ESLint 将可选链调用视为独立表达式，不允许作为语句使用。

**修复方案：**
```javascript
// 改为条件语句
if (explorerRef.current?.handleSearch) {
  explorerRef.current.handleSearch(value);
}
```

### 性能提升效果

| 优化前 | 优化后 |
|--------|--------|
| 每次渲染创建新函数 | 函数引用稳定 |
| Explorer.js 每次父渲染都重渲染 | Explorer.js 只在必要时重渲染 |
| 事件处理函数每次重新注册 | 函数引用稳定，避免重新注册 |

### 经验教训

1. **useCallback 的正确使用场景**
   - 函数作为 props 传递给子组件时
   - 函数在其他 hook 依赖项中使用时
   - 函数被存储在 ref 中时

2. **依赖数组管理**
   - 空数组 `[]`：函数永不重新创建（函数内部不依赖任何外部状态）
   - 包含依赖项：依赖变化时重新创建函数

3. **可选链调用避免作为语句使用**
   - 可选链 `?.` 只能用于返回值的表达式
   - 作为语句使用时需改为 `if` 条件判断

4. **性能优化的权衡**
   - `useCallback` 本身有性能开销
   - 适用于频繁渲染的父组件和子组件
   - 简单组件可能不需要过度优化

### 相关文件
- `spug_web/src/pages/document/index.js` - 文档管理主页（第 59-73 行）

---

**最后更新：** 2026-02-17
**适用环境：** Spug 3.0 开发和生产环境
**证书类型：** 私有 CA + 自签名证书
