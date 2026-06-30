# CA证书安装页面

本页面提供了一种简单的方式，让用户可以下载并安装Spug CA证书。

## 部署方式

### 方式1：从Spug静态文件目录提供服务

1. 将安装页面复制到Spug静态文件目录：
```bash
# 在服务器上执行
cp install-ca.html /data/spug/spug_web/build/
cp ca.crt /data/spug/spug_web/build/
```

2. 通过以下地址访问：`https://spug.internal/install-ca.html`

### 方式2：独立的Web服务器

使用Nginx提供证书服务：
```nginx
server {
    listen 80;
    server_name spug.internal;
    
    root /opt/spug-3.0/certs;
    index install-ca.html;
    
    location /install-ca.html {
        try_files $uri $uri/ =404;
    }
    
    location /ca.crt {
        types { application/x-x509-ca-cert crt; }
        add_header Content-Type application/x-x509-ca-cert;
        add_header Content-Disposition attachment;
    }
}
```

## 浏览器行为

- **Chrome/Edge**：会提示下载证书
- **Firefox**：会提示下载证书
- **Safari**：会打开证书并询问是否安装

## 移动端支持

- **iOS**：会提示在"设置 → 通用 → VPN与设备管理"中安装
- **Android**：会提示在"安全 → 加密与凭证"中安装
