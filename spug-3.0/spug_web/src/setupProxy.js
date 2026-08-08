/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
const proxy = require('http-proxy-middleware');
const http = require('http');

// 禁用 keepAlive，每次请求都建新连接
// 这样后端容器重启后不会复用死连接，无需重启 npm start
const noKeepAliveAgent = new http.Agent({ keepAlive: false });

module.exports = function (app) {
  // 代理所有 /api 请求到后端服务
  // 默认: 80 (Django runserver)
  // 覆盖方式: 设置环境变量 PROXY_TARGET，例如
  //   PROXY_TARGET=http://127.0.0.1:9001 npm start
  const target = process.env.PROXY_TARGET || 'http://127.0.0.1:8080';
  
  app.use(
    '/api',
    proxy({
      target: target,
      changeOrigin: true,
      ws: true,  // 支持 WebSocket
      agent: noKeepAliveAgent,  // 禁用连接复用，后端重启后自动建新连接
      proxyTimeout: 10000,  // 10s 超时兜底
      timeout: 30000,       // 30s 整体超时兜底
      onError: (err, req, res) => {
        console.error(`[Proxy] 连接到 ${target} 失败:`, err.message);
        console.error('[Proxy] 请确保后端服务正在运行');
        // 当代理失败时，返回 503 错误，而不是 502
        // 注意：某些情况下 res 可能不是标准的 Response 对象（如 WebSocket），需要检查
        if (res && typeof res.writeHead === 'function') {
          res.writeHead(503, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: '服务暂时不可用', target }));
        } else {
          console.error('[Proxy] Proxy error:', err.message);
        }
      }
    })
  );

  // 代理 kkFileView 预览服务请求到 Nginx（再由 Nginx 转发到 kkFileView 容器）
  // 开发环境下前端运行在 localhost:3000，iframe 中的 /kkfileview/ 请求需要代理到 Nginx
  // 生产环境下前端由 Nginx 直接服务，不存在此问题
  app.use(
    '/kkfileview',
    proxy({
      target: target,
      changeOrigin: true,
      agent: noKeepAliveAgent,
      onError: (err, req, res) => {
        console.error(`[Proxy] kkFileView 代理失败:`, err.message);
        console.error('[Proxy] 请确保 Docker 环境中的 kkFileView 容器正在运行');
        if (res && typeof res.writeHead === 'function') {
          res.writeHead(503, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'kkFileView 预览服务暂时不可用' }));
        }
      }
    })
  );
};
