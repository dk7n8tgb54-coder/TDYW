# 🟢 P3-修复方案：HTTP安全头与其他

> 对应漏洞：`安全漏洞分析/09-HTTP安全头缺失.md` (#18 #19)、`安全漏洞分析/10-其他安全建议.md` (#21)

---

## 修复项 #18 + #19：HTTP安全头补全 + 拼写修正

### 涉及文件
- `docker/config/nginx.conf`

### 修改方案

**修改前（第139-141行）：**
```nginx
add_header X-Frame-Options SAMEORIGIN always;
add_header X-Content-Options nosniff always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

**修改后：**
```nginx
# ============================================
# Security Headers
# ============================================
# Prevent clickjacking
add_header X-Frame-Options SAMEORIGIN always;

# Prevent MIME type sniffing (FIXED: was X-Content-Options)
add_header X-Content-Type-Options nosniff always;

# HSTS - force HTTPS for 1 year
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

# XSS Protection (legacy browsers)
add_header X-XSS-Protection "1; mode=block" always;

# Control Referer information leakage
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# Restrict browser features
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;

# Prevent IE from executing downloads in site context
add_header X-Download-Options "noopen" always;

# Content Security Policy
# Note: 'unsafe-inline' and 'unsafe-eval' needed for React + antd
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' wss: ws:; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self';" always;
```

### 注意事项
1. **CSP中的 `unsafe-inline` 和 `unsafe-eval`**：React + antd 需要这些，后续可通过nonce方式逐步收紧
2. **`frame-src 'self'`**：如果kkFileView iframe预览出问题，改为 `frame-src 'self' /kkfileview/`
3. **先部署观察**：建议先用 `Content-Security-Policy-Report-Only` 头观察是否有误报

---

## 修复项 #21：Redis配置支持密码

### 涉及文件
- `spug_api/spug/settings.py`

### 修改方案

**修改前：**
```python
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("127.0.0.1", 6379)],
            ...
        },
    },
}

CELERY_BROKER_URL = 'redis://127.0.0.1:6379/2'
CELERY_RESULT_BACKEND = 'redis://127.0.0.1:6379/3'
```

**修改后：**
```python
# Redis connection with optional password support
_REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '')
_REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
_REDIS_PORT = os.environ.get('REDIS_PORT', '6379')
_REDIS_URL = (
    f"redis://:{_REDIS_PASSWORD}@{_REDIS_HOST}:{_REDIS_PORT}"
    if _REDIS_PASSWORD
    else f"redis://{_REDIS_HOST}:{_REDIS_PORT}"
)

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{_REDIS_URL}/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "RETRY_ON_TIMEOUT": True,
        }
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [f"{_REDIS_URL}/0"],
            "capacity": 1000,
            "expiry": 120,
        },
    },
}

CELERY_BROKER_URL = f'{_REDIS_URL}/2'
CELERY_RESULT_BACKEND = f'{_REDIS_URL}/3'
```

### 说明
- 当 `REDIS_PASSWORD` 环境变量为空时，行为与之前完全一致（无密码连接）
- 设置密码后自动使用认证连接
- 向后兼容，不影响现有部署

---

## 补充：Nginx以root运行的修复

### 涉及文件
- `docker/config/nginx.conf`

### 修改方案

**修改前（第7行）：**
```nginx
user root;
```

**修改后：**
```nginx
user nginx;
```

> **注意**：需要确保nginx用户对静态文件目录有读取权限。在Docker中可能需要调整文件权限。

---

## 验证修复

```bash
# 1. Check security headers
curl -I -k https://localhost:8443/ 2>/dev/null | grep -i "x-content-type\|x-frame\|strict-transport\|x-xss\|referrer-policy\|content-security"
# Expected: all headers present

# 2. Verify typo fix
grep "X-Content-Options" docker/config/nginx.conf
# Expected: no results (should be X-Content-Type-Options)

# 3. Verify Redis password support
grep "REDIS_PASSWORD" spug_api/spug/settings.py
# Expected: environment variable reading
```
