# 🟢 09-HTTP安全头缺失

> 风险等级：P3
> 涉及漏洞编号：#18、#19

---

## 漏洞 #18：缺少Content-Security-Policy等HTTP安全头

### 风险描述
生产环境Nginx配置中缺少多个重要的HTTP安全响应头，降低了浏览器端的安全防护能力。

### 涉及文件

**文件：`docker/config/nginx.conf` 第139-141行**
```nginx
add_header X-Frame-Options SAMEORIGIN always;
add_header X-Content-Options nosniff always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### 缺失的安全头

| 安全头 | 作用 | 缺失风险 |
|--------|------|----------|
| `Content-Security-Policy` | 限制资源加载来源 | XSS攻击更容易成功 |
| `X-XSS-Protection` | 启用浏览器XSS过滤 | 旧浏览器无XSS防护 |
| `Referrer-Policy` | 控制Referer泄露 | 敏感URL可能泄露 |
| `Permissions-Policy` | 限制浏览器功能 | 恶意脚本可访问摄像头等 |
| `X-Download-Options` | 防止IE执行下载 | IE下载文件可能被执行 |

---

## 漏洞 #19：X-Content-Options拼写错误

### 风险描述
安全头 `X-Content-Options` 拼写错误，正确名称应为 `X-Content-Type-Options`。浏览器不会识别错误的头名称，等同于该安全头未设置。

### 涉及文件

**文件：`docker/config/nginx.conf` 第140行**
```nginx
add_header X-Content-Options nosniff always;  # ← 拼写错误！
```

**正确写法：**
```nginx
add_header X-Content-Type-Options nosniff always;
```

### 影响
- `X-Content-Type-Options: nosniff` 防止浏览器进行MIME类型嗅探
- 缺少此头时，浏览器可能将非脚本文件（如上传的图片）当作脚本执行
- 这是XSS攻击的一个辅助向量

### 注意
`config/dev/nginx.conf` 中的拼写是**正确的**：
```nginx
add_header X-Content-Type-Options nosniff always;  # ← 正确
```
说明这是生产配置中的笔误。
