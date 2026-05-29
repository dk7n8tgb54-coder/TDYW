# 生产环境私有 CA 部署指南

## 概述

本文档介绍如何在生产 Linux 服务器上部署使用私有 CA 签发的 HTTPS 证书。

## 架构说明

```
┌─────────────────┐
│  Root CA        │  (在管理服务器上生成一次)
│  Spug-Root-CA   │
└────────┬────────┘
         │ 签发
         ↓
┌─────────────────┐
│  Server Cert    │  (部署到生产服务器)
│  spug.internal  │
└─────────────────┘
         │
         ↓
┌─────────────────┐
│  Clients        │  (安装 Root CA)
│  Browsers       │  → 自动信任 Server Cert
└─────────────────┘
```

## 步骤 1: 在管理服务器生成 CA（已完成）

已经在 Windows 开发机上生成：
- CA 证书: `certs/ca/ca.crt`
- CA 私钥: `certs/ca/ca.key`
- 服务器证书: `certs/prod/spug.crt`
- 服务器私钥: `certs/prod/spug.key`

**证书信息：**
- CA 有效期：10 年（2026-02-15 至 2036-02-13）
- 服务器证书有效期：10 年
- 支持域名：spug.internal, spug, localhost
- 支持 IP：192.168.1.100

## 步骤 2: 上传证书到生产服务器

### 2.1 创建目录结构

```bash
# SSH 登录到生产服务器
ssh root@spug-server

# 创建证书目录
mkdir -p /opt/spug-3.0/certs/ca
mkdir -p /opt/spug-3.0/certs/prod
```

### 2.2 上传证书文件

**方法 1: 使用 SCP**
```bash
# 从 Windows 开发机执行
scp e:\TDYW\spug-3.0\certs\ca\ca.crt root@spug-server:/opt/spug-3.0/certs/ca/
scp e:\TDYW\spug-3.0\certs\prod\spug.crt root@spug-server:/opt/spug-3.0/certs/prod/
scp e:\TDYW\spug-3.0\certs\prod\spug.key root@spug-server:/opt/spug-3.0/certs/prod/
```

**方法 2: 使用 rsync**
```bash
rsync -avz e:/TDYW/spug-3.0/certs/ root@spug-server:/opt/spug-3.0/certs/
```

**方法 3: 使用 FTP/SFTP**
- 使用 WinSCP、FileZilla 等 GUI 工具上传

### 2.3 设置文件权限

```bash
# 在生产服务器上执行
chmod 600 /opt/spug-3.0/certs/prod/spug.key
chmod 644 /opt/spug-3.0/certs/prod/spug.crt
chmod 644 /opt/spug-3.0/certs/ca/ca.crt

# 验证权限
ls -la /opt/spug-3.0/certs/prod/
ls -la /opt/spug-3.0/certs/ca/
```

## 步骤 3: 启动生产环境

### 3.1 上传配置文件（如果还没上传）

```bash
# 上传 docker-compose.prod.yml
scp e:\TDYW\spug-3.0\docker-compose.prod.yml root@spug-server:/opt/spug-3.0/

# 上传 Nginx 配置
scp e:\TDYW\spug-3.0\config\prod\nginx.conf root@spug-server:/opt/spug-3.0/config/prod/
```

### 3.2 创建必要的 Docker Volumes

```bash
# 在生产服务器上执行
cd /opt/spug-3.0

# 创建 Volumes（如果不存在）
docker volume create spug-3.0_mysql-data
docker volume create spug-3.0_frontend-data
docker volume create spug-3.0_repos-data
docker volume create spug-3.0_backend-data
docker volume create spug-3.0_document-files
```

### 3.3 配置环境变量（可选）

创建 `.env` 文件：
```bash
cat > /opt/spug-3.0/.env << 'EOF'
# 数据库密码
MYSQL_PASSWORD=your_secure_password_here
MYSQL_ROOT_PASSWORD=your_root_password_here

# 允许的主机
ALLOWED_HOSTS=spug.internal,spug,192.168.1.100,localhost

# Django Secret Key（生成随机密钥）
DJANGO_SECRET_KEY=$(openssl rand -hex 50)
EOF

chmod 600 /opt/spug-3.0/.env
```

### 3.4 启动服务

```bash
cd /opt/spug-3.0

# 停止旧容器（如果运行）
docker-compose -f docker-compose.prod.yml down

# 启动新容器
docker-compose -f docker-compose.prod.yml up -d

# 查看日志
docker-compose -f docker-compose.prod.yml logs -f
```

### 3.5 验证服务状态

```bash
# 检查容器状态
docker ps

# 测试 HTTPS
curl -k https://spug.internal

# 测试证书
openssl s_client -connect spug.internal:443 -servername spug.internal
```

## 步骤 4: 分发 CA 证书到客户端

### 4.1 准备客户端安装包

客户端安装包位于：`certs/client-dist/`

包含文件：
- `ca.crt` - Root CA 证书
- `install-ca.bat` - Windows 自动安装脚本
- `uninstall-ca.bat` - Windows 卸载脚本
- `README.md` - 详细安装说明

### 4.2 Windows 客户端安装

**方法 1: 自动安装（推荐）**
1. 发送 `client-dist` 文件夹给用户
2. 用户右键 `install-ca.bat`
3. 选择 "以管理员身份运行"
4. 等待完成提示

**方法 2: 手动安装**
1. 双击 `ca.crt`
2. 点击 "安装证书"
3. 选择 "本地计算机"
4. 点击 "下一步"
5. 选择 "将所有证书放入下列存储"
6. 点击 "浏览" → 选择 "受信任的根证书颁发机构"
7. 点击 "确定" → "下一步" → "完成"

**验证安装：**
- 打开浏览器访问 https://spug.internal
- 应该显示安全锁图标，无警告

### 4.3 Linux 客户端安装

**Ubuntu/Debian:**
```bash
# 复制证书
sudo cp ca.crt /usr/local/share/ca-certificates/spug-ca.crt

# 更新证书库
sudo update-ca-certificates

# 验证
curl https://spug.internal
```

**CentOS/RHEL:**
```bash
# 复制证书
sudo cp ca.crt /etc/pki/ca-trust/source/anchors/spug-ca.crt

# 更新证书库
sudo update-ca-trust

# 验证
curl https://spug.internal
```

### 4.4 macOS 客户端安装

```bash
# 添加到系统钥匙串
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.crt

# 验证
curl https://spug.internal
```

### 4.5 Firefox 浏览器（使用独立的证书存储）

1. 打开 Firefox
2. 菜单 → 设置 → 隐私与安全
3. 向下滚动到 "证书"
4. 点击 "查看证书"
5. 切换到 "证书颁发机构" 标签
6. 点击 "导入"
7. 选择 `ca.crt`
8. 勾选 "信任此证书颁发机构来标识网站"
9. 点击 "确定"

## 步骤 5: 验证部署

### 5.1 服务器端验证

```bash
# 检查 Nginx 配置
docker exec spug-prod nginx -t

# 检查证书信息
docker exec spug-prod openssl x509 -in /etc/nginx/certs/spug.crt -noout -subject -issuer -dates

# 检查 HTTPS 服务
curl -k https://spug.internal
```

### 5.2 客户端验证

**Windows:**
1. 打开 https://spug.internal
2. 检查地址栏是否显示锁图标 🔒
3. 点击锁图标 → "连接是安全的" → "证书是有效的"

**Linux/macOS:**
```bash
# 验证证书链
openssl s_client -connect spug.internal:443 -servername spug.internal -showcerts

# 检查验证结果（应该返回 0）
openssl s_client -connect spug.internal:443 -verify_return_error 2>&1 | grep -q "Verify return code: 0"
echo $?
```

## 步骤 6: 批量部署客户端（可选）

### 使用组策略（Windows AD 域环境）

1. 打开 "组策略管理" (gpmc.msc)
2. 创建或编辑 GPO
3. 导航到：计算机配置 → 策略 → Windows 设置 → 安全设置 → 公钥策略 → 受信任的根证书颁发机构
4. 右键 → 导入
5. 选择 `ca.crt`
6. 链接 GPO 到 OU

### 使用 Ansible（大规模部署）

```yaml
# playbook.yml
---
- name: Install Spug CA certificate
  hosts: all
  become: yes
  tasks:
    - name: Copy CA certificate
      copy:
        src: ca.crt
        dest: /usr/local/share/ca-certificates/spug-ca.crt

    - name: Update CA certificates (Debian/Ubuntu)
      command: update-ca-certificates
      when: ansible_os_family == "Debian"

    - name: Update CA certificates (RHEL/CentOS)
      command: update-ca-trust
      when: ansible_os_family == "RedHat"
```

运行：
```bash
ansible-playbook playbook.yml
```

## 证书维护

### 更新证书（当前证书 10 年后过期）

```bash
# 1. 在管理服务器重新生成
cd e:\TDYW\spug-3.0\certs
powershell -ExecutionPolicy Bypass -File setup-ca.ps1

# 2. 上传新的服务器证书到生产服务器
scp e:\TDYW\spug-3.0\certs\prod\spug.crt root@spug-server:/opt/spug-3.0/certs/prod/

# 3. 重启服务
ssh root@spug-server "docker-compose -f /opt/spug-3.0/docker-compose.prod.yml restart"

# 4. 客户端无需重新安装 CA 证书（如果 CA 未过期）
```

### 撤销证书（如果私钥泄露）

1. 创建证书撤销列表 (CRL) - 高级操作
2. 配置 Nginx 使用 CRL
3. 或直接重新签发新证书

## 故障排查

### 问题 1: 浏览器仍然显示不安全

**检查：**
```bash
# 1. 确认客户端已安装 CA 证书
certmgr.msc  # Windows 查看证书管理器

# 2. 清除浏览器缓存并重启

# 3. 尝试其他浏览器

# 4. 检查证书详情
- Subject: CN=spug.internal
- Issuer: CN=Spug-Root-CA
- NotAfter: 应该在未来
```

### 问题 2: 无法访问 HTTPS 服务

**检查：**
```bash
# 1. 检查容器状态
docker ps | grep spug-prod

# 2. 检查端口映射
docker port spug-prod

# 3. 检查防火墙
sudo firewall-cmd --list-ports  # CentOS
sudo ufw status                # Ubuntu

# 4. 检查 Nginx 配置
docker exec spug-prod nginx -t

# 5. 查看 Nginx 错误日志
docker logs spug-prod
docker exec spug-prod tail -f /var/log/nginx/error.log
```

### 问题 3: Nginx 启动失败

**检查：**
```bash
# 1. 验证证书文件存在
docker exec spug-prod ls -la /etc/nginx/certs/

# 2. 检查证书权限
docker exec spug-prod ls -la /etc/nginx/certs/spug.key

# 3. 测试 Nginx 配置
docker exec spug-prod nginx -t

# 4. 查看 Nginx 详细错误
docker logs spug-prod 2>&1 | grep nginx
```

## 安全建议

1. **备份 CA 私钥**
   ```bash
   # 将 ca.key 备份到安全位置
   # 可以加密存储或离线存储
   # 不要泄露给他人
   ```

2. **定期检查证书有效期**
   ```bash
   # 设置监控，在过期前 90 天提醒
   # 可以使用 Nagios、Zabbix 等监控系统
   ```

3. **限制 CA 私钥访问**
   ```bash
   # 只有授权人员可以访问 ca.key
   # 使用文件权限控制
   chmod 600 ca.key
   ```

4. **记录证书签发**
   ```bash
   # 维护证书签发记录
   # 记录每个证书的用途、有效期、签发时间
   ```

## 参考资料

- [OpenSSL 文档](https://www.openssl.org/docs/)
- [Nginx SSL 配置](http://nginx.org/en/docs/http/configuring_https_servers.html)
- [Mozilla SSL 配置生成器](https://ssl-config.mozilla.org/)

## 支持

如有问题，请联系 IT 支持团队。
