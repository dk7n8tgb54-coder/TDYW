/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import http from 'libs/http';
import React from 'react';

/**
 * 文件图标映射 - emoji 图标（与资料管理统一）
 */
export const FileIconMap = {
  file: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="文件">📄</span>,
  image: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="图片">🖼️</span>,
  pdf: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="PDF">📄</span>,
  word: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="Word">📝</span>,
  excel: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="Excel">📊</span>,
  ppt: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="PPT">📋</span>,
  video: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="视频">🎬</span>,
  audio: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="音频">🎵</span>,
  archive: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="压缩包">📦</span>,
  text: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="文本">📃</span>,
  code: <span style={{ fontSize: 20, marginRight: 8 }} role="img" aria-label="代码">💻</span>,
};

/**
 * 获取回收站列表
 * @param {Object} params - 查询参数
 * @param {number} params.page - 页码
 * @param {number} params.page_size - 每页数量
 * @param {string} params.keyword - 搜索关键词
 * @param {string} params.space - 空间类型：private/public/all
 * @returns {Promise<{items: Array, total: number, page: number, page_size: number}>}
 */
/**
 * 【P2修复】包装HTTP请求，添加统一错误处理
 * @param {Promise} promise - HTTP请求Promise
 * @param {string} context - 请求上下文描述
 * @returns {Promise} 处理后的Promise
 */
function wrapRequest(promise, context = '') {
  return promise.catch(error => {
    // 统一错误处理和转换
    if (error.response) {
      const { status, data } = error.response;
      const errorMessage = data?.error || data?.message || `请求失败 (${status})`;
      const enhancedError = new Error(errorMessage);
      enhancedError.status = status;
      enhancedError.code = data?.code;
      enhancedError.originalError = error;
      throw enhancedError;
    } else if (error.request) {
      // 请求已发出但没有收到响应
      const networkError = new Error('网络错误，请检查网络连接');
      networkError.originalError = error;
      throw networkError;
    }
    // 其他错误
    throw error;
  });
}

export function getRecycleBinList(params, signal) {
  // 【P2修复】支持AbortController signal
  return wrapRequest(http.get('/api/document/recycle-bin/', { params, signal }), '获取回收站列表');
}

/**
 * 恢复文件
 * @param {Object} data - 恢复参数
 * @param {Array<number>} data.file_ids - 要恢复的文件ID列表
 * @param {number} [data.target_folder_id] - 目标文件夹ID（custom模式必填）
 * @param {number} [data.current_folder_id] - 当前文件夹ID（current模式使用）
 * @param {string} [data.restore_mode='original'] - 恢复模式：original/current/custom
 * @param {string} [data.idempotent_key] - 幂等键
 * @returns {Promise<{success_count: number, failed_count: number, details: Array}>}
 */
export function restoreFiles(data) {
  return wrapRequest(http.post('/api/document/recycle-bin/restore/', data), '恢复文件');
}

/**
 * 恢复文件夹
 * @param {Object} data - 恢复参数
 * @param {Array<number>} data.folder_ids - 要恢复的文件夹ID列表
 * @param {number} [data.target_parent_id] - 目标父文件夹ID（custom模式必填）
 * @param {string} [data.restore_mode='original'] - 恢复模式：original/root/custom
 * @param {string} [data.idempotent_key] - 幂等键
 * @returns {Promise<{success_count: number, failed_count: number, details: Array}>}
 */
export function restoreFolders(data) {
  return wrapRequest(http.post('/api/document/recycle-bin/folder-restore/', data), '恢复文件夹');
}

/**
 * 彻底删除文件
 * @param {Object} data - 删除参数
 * @param {Array<number>} data.file_ids - 要删除的文件ID列表
 * @param {boolean} [data.async_mode=false] - 是否强制异步模式
 * @returns {Promise<{async: boolean, success_count?: number, failed_count?: number, freed_space?: number, task_id?: string, message?: string}>}
 */
export function permanentDeleteFiles(data) {
  return wrapRequest(http.post('/api/document/recycle-bin/permanent/', data), '彻底删除文件');
}

/**
 * 彻底删除文件夹
 * @param {Object} data - 删除参数
 * @param {Array<number>} data.folder_ids - 要删除的文件夹ID列表
 * @param {boolean} [data.async_mode=false] - 是否强制异步模式
 * @returns {Promise<{async: boolean, success_count?: number, failed_count?: number, freed_space?: number, task_id?: string, message?: string}>}
 */
export function permanentDeleteFolders(data) {
  return wrapRequest(http.post('/api/document/recycle-bin/folder-permanent/', data), '彻底删除文件夹');
}

/**
 * 获取回收站统计信息
 * @returns {Promise<{total_count: number, total_size: number, private_count: number, private_size: number, public_count: number, public_size: number, expiring_soon: number, retention_days: number}>}
 */
export function getRecycleBinStats() {
  return wrapRequest(http.get('/api/document/recycle-bin/stats/'), '获取回收站统计');
}

/**
 * 格式化文件大小
 * @param {number} bytes - 字节数
 * @returns {string} 格式化后的文件大小
 * @deprecated 请直接使用 @/utils/format 中的 formatFileSize
 */
export function formatFileSize(bytes) {
  // 【2.3重构】使用公共工具函数
  const { formatFileSize: _formatFileSize } = require('@/utils/format');
  return _formatFileSize(bytes);
}

/**
 * 获取文件图标类型
 * @param {string} fileType - 文件MIME类型
 * @param {string} fileName - 文件名（用于后备判断）
 * @returns {string} 图标类型
 */
export function getFileIcon(fileType, fileName) {
  if (!fileType && !fileName) return 'file';

  const type = (fileType || '').toLowerCase();
  const name = (fileName || '').toLowerCase();
  // 【P2修复】改进扩展名提取逻辑，正确处理隐藏文件
  const ext = extractFileExtension(name);

  if (type.includes('image') || ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(ext)) {
    return 'image';
  }
  if (type.includes('pdf') || ext === 'pdf') {
    return 'pdf';
  }
  if (type.includes('word') || ['doc', 'docx'].includes(ext)) {
    return 'word';
  }
  if (type.includes('excel') || type.includes('spreadsheet') || ['xls', 'xlsx', 'csv'].includes(ext)) {
    return 'excel';
  }
  if (type.includes('powerpoint') || type.includes('presentation') || ['ppt', 'pptx'].includes(ext)) {
    return 'ppt';
  }
  if (type.includes('video') || ['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'].includes(ext)) {
    return 'video';
  }
  if (type.includes('audio') || ['mp3', 'wav', 'ogg', 'flac', 'aac'].includes(ext)) {
    return 'audio';
  }
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) {
    return 'archive';
  }
  if (['txt', 'log', 'md'].includes(ext) || type.includes('text') || type.includes('plain')) {
    return 'text';
  }
  if (['js', 'ts', 'jsx', 'tsx', 'vue', 'py', 'java', 'go', 'cpp', 'c', 'h', 'html', 'css', 'json', 'xml'].includes(ext)) {
    return 'code';
  }
  return 'file';
}

/**
 * 格式化文件类型显示
 * 将MIME类型转换为友好的中文显示
 * @param {string} fileType - 文件MIME类型
 * @param {string} fileName - 文件名（用于后备判断）
 * @returns {string} 格式化后的文件类型
 */
export function formatFileType(fileType, fileName) {
  if (!fileType && !fileName) return '文件';
  
  const type = (fileType || '').toLowerCase();
  const name = (fileName || '').toLowerCase();
  const ext = extractFileExtension(name);
  
  // Office 文档类型
  if (type.includes('word') || ['doc', 'docx'].includes(ext)) {
    return 'Word 文档';
  }
  if (type.includes('excel') || type.includes('spreadsheet') || ['xls', 'xlsx', 'csv'].includes(ext)) {
    return 'Excel 表格';
  }
  if (type.includes('powerpoint') || type.includes('presentation') || ['ppt', 'pptx'].includes(ext)) {
    return 'PPT 演示文稿';
  }
  
  // 常见类型
  if (type.includes('pdf') || ext === 'pdf') {
    return 'PDF 文档';
  }
  if (type.includes('image') || ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(ext)) {
    return '图片';
  }
  if (type.includes('video') || ['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'].includes(ext)) {
    return '视频';
  }
  if (type.includes('audio') || ['mp3', 'wav', 'ogg', 'flac', 'aac'].includes(ext)) {
    return '音频';
  }
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) {
    return '压缩包';
  }
  if (['txt', 'log', 'md'].includes(ext) || type.includes('text') || type.includes('plain')) {
    return '文本文件';
  }
  if (['js', 'ts', 'jsx', 'tsx', 'vue', 'py', 'java', 'go', 'cpp', 'c', 'h', 'html', 'css', 'json', 'xml'].includes(ext)) {
    return '代码文件';
  }
  
  // 返回扩展名大写作为后备
  if (ext) {
    return ext.toUpperCase() + ' 文件';
  }
  
  return '文件';
}

/**
 * 【P2修复】提取文件扩展名（正确处理隐藏文件）
 * @param {string} fileName - 文件名
 * @returns {string} 扩展名（不含点号）
 */
function extractFileExtension(fileName) {
  if (!fileName || typeof fileName !== 'string') {
    return '';
  }
  
  // 移除路径部分（如果有）
  const baseName = fileName.split('/').pop().split('\\').pop();
  
  // 查找最后一个点号
  const lastDotIndex = baseName.lastIndexOf('.');
  
  // 如果点号在开头（隐藏文件如 .bashrc）或不存在，返回空字符串
  if (lastDotIndex <= 0) {
    return '';
  }
  
  return baseName.slice(lastDotIndex + 1);
}

/**
 * 生成唯一幂等键
 * @returns {string} 幂等键
 */
export function generateIdempotentKey() {
  return `restore_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * 【方案一新增】查询异步任务状态
 * @param {string} taskId - 任务ID
 * @returns {Promise<{task_id: string, state: string, ready: boolean, successful: boolean, result: object, error: string, progress: number, processed: number, total: number}>}
 */
export function getTaskStatus(taskId) {
  return wrapRequest(http.get('/api/document/recycle-bin/task-status/', { params: { task_id: taskId } }), '查询任务状态');
}

/**
 * 获取已删除文件夹内的内容
 * @param {Object} params - 查询参数
 * @param {number} params.folder_id - 文件夹ID
 * @param {string} params.space - 空间类型：private/public
 * @param {number} params.page - 页码
 * @param {number} params.page_size - 每页数量
 * @returns {Promise<{items: Array, total: number, page: number, page_size: number, folder_info: Object, parent_chain: Array}>}
 */
export function getFolderContent(params) {
  return wrapRequest(http.get('/api/document/recycle-bin/folder-content/', { params }), '获取文件夹内容');
}
