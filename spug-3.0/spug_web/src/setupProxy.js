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

  // 慢接口专用代理：数据质量巡检同步执行约 15-20s，不能走通用 10s proxyTimeout
  // 注意：必须注册在通用 /api 代理之前，Express 按注册顺序匹配
  app.use(
    '/api/alert/data-quality',
    proxy({
      target: target,
      changeOrigin: true,
      agent: noKeepAliveAgent,
      proxyTimeout: 130000, // 与 axios 默认 120s 对齐，略留余量
      timeout: 130000,
      onError: (err, req, res) => {
        console.error(`[Proxy] 连接到 ${target} 失败:`, err.message);
        if (res && typeof res.writeHead === 'function') {
          res.writeHead(503, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: '服务暂时不可用', target }));
        }
      }
    })
  );

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

  // 代理 ONLYOFFICE Docs 请求到 Nginx（再由 Nginx 转发到 onlyoffice 容器）
  // 与 /kkfileview 同理：前端跑在 localhost:3000 时，编辑器 api.js、静态
  // 资源与协同编辑 WebSocket 都走 /onlyoffice/ 同源路径，必须代理到
  // tdyw-test 的 Nginx（由它做子路径转发与 WS upgrade）。协同编辑是
  // WebSocket 长连接，ws: true 不可省。
  // 代理 ONLYOFFICE Docs 请求到 Nginx（再由 Nginx 转发到 onlyoffice 容器）
  // 与 /kkfileview 同理：前端跑在 localhost:3000 时，编辑器 api.js、静态
  // 资源与协同编辑 WebSocket 都走 /onlyoffice/ 同源路径。注意目标必须是
  // tdyw-test 的 Nginx（8080，负责 /onlyoffice 子路径剥离与 WS upgrade），
  // 不能跟随 PROXY_TARGET 直连 gunicorn——gunicorn 没有该路由。
  // changeOrigin 必须为 false：DS 按请求 Host 生成缓存文件绝对 URL，
  // 需要 Nginx 看到浏览器真实 Host（含端口）才能让缓存 URL 与浏览器
  // 同源（跨源会被浏览器拦截，表现为"下载失败"）。
  // 不能传 keepAlive:false 的自定义 agent——会干扰 WebSocket 升级管道，
  // 表现为 101 握手成功后 socket 立即断开、编辑器无限重连。
  app.use(
    '/onlyoffice',
    proxy({
      target: 'http://127.0.0.1:8080',
      changeOrigin: false,
      ws: true,
      proxyTimeout: 3600000, // 协同编辑 WebSocket 长连接
      timeout: 3600000,
      onError: (err, req, res) => {
        console.error(`[Proxy] ONLYOFFICE 代理失败:`, err.message);
        console.error('[Proxy] 请确保 Docker 环境中的 onlyoffice 容器正在运行');
        if (res && typeof res.writeHead === 'function') {
          res.writeHead(503, { 'Content-Type': 'text/plain' });
          res.end('ONLYOFFICE 文档服务暂时不可用');
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
