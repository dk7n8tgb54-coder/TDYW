/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import http from 'axios'
import history from './history'
import { X_TOKEN } from './functools';
import { message } from 'antd';

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
        message.error(result);
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
    result = `请求失败: ${response.status} ${response.statusText}`
  }
  message.error(result);
  return Promise.reject(result)
}

// 请求拦截器
http.interceptors.request.use(request => {
  request.isInternal = request.url.startsWith('/api/');
  if (request.isInternal) {
    request.headers['X-Token'] = X_TOKEN
  }
  request.timeout = request.timeout || 120000;
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
  message.error(result);
  return Promise.reject(result)
});

export default http;
