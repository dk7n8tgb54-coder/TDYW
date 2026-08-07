/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import http from 'axios'
import history from './history'
import { X_TOKEN } from './functools';
import { message } from 'antd';
import { getSystemFolder, shouldUseSystemFolder } from './systemFolderContext';

// 错误去重：2 秒内相同错误消息只显示一次，防止空间切换等场景重复弹窗
let _lastErrorMsg = null;
let _lastErrorTime = 0;
function showErrorOnce(msg) {
  const now = Date.now();
  if (msg === _lastErrorMsg && now - _lastErrorTime < 2000) {
    return; // 2 秒内相同消息已展示，跳过
  }
  _lastErrorMsg = msg;
  _lastErrorTime = now;
  message.error(msg);
}

// response处理
function handleResponse(response) {
  let result;
  if (response.status === 401) {
    result = '会话过期，请重新登录';
    if (history.location.pathname !== '/') {
      history.push('/', {from: history.location})
    } else {
      return Promise.reject()
    }
  } else if (response.status === 200) {
    // 处理二进制响应（arraybuffer/blob）
    if (response.config.responseType === 'arraybuffer' || response.config.responseType === 'blob') {
      const contentType = (response.headers['content-type'] || response.headers['Content-Type'] || '').toLowerCase();
      // 后端返回了JSON错误（以二进制形式传输）
      if (contentType.includes('application/json')) {
        try {
          const text = typeof response.data === 'string'
            ? response.data
            : new TextDecoder().decode(response.data);
          const errorData = JSON.parse(text);
          result = errorData.error || '操作失败';
        } catch (e) {
          result = '操作失败';
        }
        showErrorOnce(result);
        return Promise.reject(result);
      }
      // PDF/文件等二进制响应，直接透传
      return Promise.resolve(response);
    }
    if (response.data.error) {
      result = response.data.error
    } else if (response.data.hasOwnProperty('data')) {
      // 如果data是空字符串，返回空对象而不是空字符串
      const data = response.data.data === '' ? {} : response.data.data;
      return Promise.resolve(data)
    } else if (!response.config.isInternal) {
      return Promise.resolve(response.data)
    } else {
      result = '无效的数据格式'
    }
  } else {
    // 非 200 状态码：二进制响应（arraybuffer/blob）可能包含后端返回的 JSON 错误
    // 例如导出接口返回 400 + JsonResponse，需要解析出具体错误信息
    if (response.config.responseType === 'arraybuffer' || response.config.responseType === 'blob') {
      const contentType = (response.headers['content-type'] || response.headers['Content-Type'] || '').toLowerCase();
      if (contentType.includes('application/json')) {
        try {
          const text = typeof response.data === 'string'
            ? response.data
            : new TextDecoder().decode(response.data);
          const errorData = JSON.parse(text);
          result = errorData.error || `请求失败: ${response.status} ${response.statusText}`;
        } catch (e) {
          result = `请求失败: ${response.status} ${response.statusText}`;
        }
      } else {
        result = `请求失败: ${response.status} ${response.statusText}`;
      }
    } else {
      result = `请求失败: ${response.status} ${response.statusText}`;
    }
  }
  // 允许调用方通过 config.skipErrorNotification=true 抑制错误弹窗
  // 用于空间切换等可能产生过期请求的场景，避免重复提示
  if (!response.config?.skipErrorNotification) {
    showErrorOnce(result);
  }
  return Promise.reject(result)
}

// 请求拦截器
http.interceptors.request.use(request => {
  request.isInternal = request.url.startsWith('/api/');
  if (request.isInternal) {
    request.headers['X-Token'] = X_TOKEN
  }
  request.timeout = request.timeout || 120000;

  // 【党建文档】激活 system_folder 上下文时，自动为 /api/document/* 请求注入参数
  const activeCode = getSystemFolder();
  const shouldInjectSystemFolder = shouldUseSystemFolder(history.location.pathname);
  if (activeCode && shouldInjectSystemFolder && request.isInternal && request.url.indexOf('/api/document/') === 0) {
    // GET / DELETE：注入到 query params
    if (['get', 'delete', 'head'].includes(request.method)) {
      request.params = request.params || {};
      if (request.params.system_folder === undefined) {
        request.params.system_folder = activeCode;
      }
    } else {
      // POST / PUT：multipart 注入 FormData，JSON 注入 body
      const contentType = (request.headers && (request.headers['Content-Type'] || request.headers['content-type'])) || '';
      if (contentType.indexOf('multipart/form-data') >= 0 && request.data instanceof FormData) {
        if (!request.data.has('system_folder')) {
          request.data.append('system_folder', activeCode);
        }
      } else if (request.data && typeof request.data === 'object' && !(request.data instanceof FormData)) {
        if (request.data.system_folder === undefined) {
          request.data = { ...request.data, system_folder: activeCode };
        }
      } else if (request.data === undefined || request.data === null) {
        request.data = { system_folder: activeCode };
      }
    }
  }

  return request;
});

// 返回拦截器
http.interceptors.response.use(response => {
  return handleResponse(response)
}, error => {
  if (error.response) {
    return handleResponse(error.response)
  }
  // 【错误友好化】将技术错误转换为用户易懂的提示
  let errorMsg = error.message || '请求异常';
  if (errorMsg.includes('timeout')) {
    errorMsg = '请求超时，文件较大请重试';
  } else if (errorMsg.includes('Network Error')) {
    errorMsg = '网络连接失败，请检查网络后重试';
  }
  const result = '请求异常: ' + errorMsg;
  showErrorOnce(result);
  return Promise.reject(result)
});

export default http;
