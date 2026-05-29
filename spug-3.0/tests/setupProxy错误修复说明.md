# setupProxy.js 错误修复说明

## 问题描述

### 问题 1: WebSocket 错误处理

在开发环境中，WebSocket 代理连接失败时出现以下错误：

```
TypeError: res.writeHead is not a function
    at ProxyServer.onError (E:\TDYW\spug-3.0\spug_web\src\setupProxy.js:18:13)
```

### 问题 2: 代理目标端口错误

前端开发服务器无法连接到后端 API：

```
[HPM] Error occurred while trying to proxy request /api/account/login/ from localhost:3000 to http://localhost:8080 (ECONNREFUSED)
```

## 问题原因

### 问题 1: WebSocket 错误处理

当 WebSocket 连接失败时，`onError` 回调中的 `res` 参数可能不是标准的 HTTP Response 对象，而是 WebSocket 升级请求的对象，因此没有 `writeHead` 方法。

### 问题 2: 代理目标端口错误

代理目标端口配置为 `8080`，但后端服务在 Docker 容器中运行在 **80 端口**（nginx 端口）。

## 修复方案

### 修复 1: WebSocket 错误处理

在 `onError` 回调中添加类型检查，确保 `res` 对象存在且具有 `writeHead` 方法。

#### 修复前

```javascript
onError: (err, req, res) => {
  // 当代理失败时，返回 503 错误，而不是 502
  res.writeHead(503, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: '服务暂时不可用' }));
}
```

#### 修复后

```javascript
onError: (err, req, res) => {
  // 当代理失败时，返回 503 错误，而不是 502
  // 注意：某些情况下 res 可能不是标准的 Response 对象（如 WebSocket），需要检查
  if (res && typeof res.writeHead === 'function') {
    res.writeHead(503, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: '服务暂时不可用' }));
  } else {
    console.error('[Proxy] Proxy error:', err.message);
  }
}
```

### 修复 2: 代理目标端口

将代理目标端口从 `8080` 修改为 `80`（正确的 Docker 容器 nginx 端口）。

#### 修复前

```javascript
target: 'http://localhost:8080', // 修改为一个不太可能被占用的端口
```

#### 修复后

```javascript
target: 'http://localhost:80', // Docker 容器中的 nginx 端口
```

## 修复文件

- **文件路径**: `spug_web/src/setupProxy.js`
- **修改行数**: 13, 16-24
- **修改内容**:
  - 修复代理目标端口（8080 → 80）
  - 添加类型检查

## 影响范围

此修复仅影响开发环境的代理服务器，不影响生产环境。

## 验证

### 验证 1: WebSocket 错误处理

修复后，WebSocket 连接失败时：
- 如果 `res` 是标准 Response 对象，返回 503 错误
- 如果 `res` 不是标准 Response 对象，在控制台输出错误信息
- 不再抛出 `TypeError: res.writeHead is not a function` 错误

### 验证 2: 代理目标端口

修复后：
- 前端开发服务器可以正确连接到后端 API
- 不再出现 `ECONNREFUSED` 错误

**验证命令**:
```bash
# 验证后端服务是否正常运行
docker exec spug sh -c "curl -s http://localhost/api/account/login/ -o /dev/null -w '%{http_code}'"
# 预期输出: 200
```

## 相关信息

- **错误类型**: 开发环境代理错误
- **影响功能**:
  - WebSocket 连接失败时的错误处理
  - API 请求代理
- **优先级**: 中（影响开发体验）
- **修复时间**: 2026-03-01

---

**修复人员**: Auto AI Assistant
**修复时间**: 2026-03-01
**文档版本**: v1.1

