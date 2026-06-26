/**
 * 公共导出文件下载工具
 *
 * 职责：
 * - 使用现有 http 封装发送请求（responseType: arraybuffer）
 * - 从 Content-Disposition 中解析文件名
 * - 根据 Content-Type 创建 Blob 并触发浏览器下载
 * - 统一处理 loading、空数据、后端错误（http 拦截器已处理 JSON 错误透传）
 *
 * 示例：
 *   exportFile({
 *     url: '/api/fault/faultrecord/export/',
 *     method: 'get',
 *     params: store.getExportParams(),
 *     defaultFilename: '故障处置记录.xlsx',
 *   });
 */
import http from './http';
import { message } from 'antd';

/**
 * 从 Content-Disposition 响应头解析文件名
 * 兼容 RFC 5987（filename*=UTF-8''xxx）与传统 filename="xxx"
 */
function parseFilename(contentDisposition, defaultFilename) {
  if (!contentDisposition) return defaultFilename;
  // 优先匹配 filename*=UTF-8''xxxx
  const star = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition);
  if (star && star[1]) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch (e) {
      return star[1].trim();
    }
  }
  // 回退到 filename="xxxx"
  const plain = /filename="?([^";]+)"?/i.exec(contentDisposition);
  if (plain && plain[1]) {
    return plain[1].trim();
  }
  return defaultFilename;
}

/**
 * 触发浏览器下载
 */
function triggerDownload(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // 释放对象 URL，避免内存泄漏
  setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

/**
 * 导出文件
 * @param {Object} options
 * @param {string} options.url - 请求地址
 * @param {string} [options.method='get'] - 请求方法
 * @param {Object} [options.params] - query 参数（GET）
 * @param {Object} [options.data] - body 参数（POST）
 * @param {string} options.defaultFilename - 默认文件名（后端未返回时使用）
 * @param {number} [options.timeout=60000] - 超时时间，导出较大可适当延长
 * @param {string} [options.loadingText] - 加载提示文案，传入则显示 loading（用于 PDF 等耗时导出）
 * @param {boolean} [options.showSuccess=true] - 是否在成功后显示提示
 * @returns {Promise<void>}
 */
export async function exportFile(options) {
  const {
    url,
    method = 'get',
    params,
    data,
    defaultFilename = '导出文件',
    timeout = 60000,
    loadingText,
    showSuccess = true,
  } = options;

  const hide = loadingText ? message.loading(loadingText) : null;
  try {
    const response = await http({
      url,
      method,
      params,
      data,
      responseType: 'arraybuffer',
      timeout,
    });
    // http 拦截器对二进制响应直接透传 response（非 data）
    const resData = response.data;
    const headers = response.headers || {};
    const contentType = (headers['content-type'] || headers['Content-Type'] || '').toLowerCase();

    // 后端可能返回空内容
    if (!resData || resData.byteLength === 0) {
      message.warning('当前筛选条件下没有可导出的数据');
      return;
    }

    const filename = parseFilename(
      headers['content-disposition'] || headers['Content-Disposition'],
      defaultFilename
    );
    const blob = new Blob([resData], { type: contentType || 'application/octet-stream' });
    triggerDownload(blob, filename);
    if (showSuccess) message.success('导出成功');
  } catch (e) {
    // http 拦截器已对错误（含二进制中的 JSON 错误）做了 message.error 提示
    // 这里仅兜底，避免未捕获异常
    if (e) console.error('[exportFile] 导出失败:', e);
  } finally {
    if (hide) hide();
  }
}

export default exportFile;
