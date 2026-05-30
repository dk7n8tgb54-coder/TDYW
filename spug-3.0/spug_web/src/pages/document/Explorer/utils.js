/**
 * Explorer 工具函数
 * 严格遵循原始 Explorer.js 的实现
 */
import React from 'react';
// 【2.3重构】使用公共工具函数
import { formatFileSize as _formatFileSize, formatDate as _formatDate } from '@/utils/format';

// 生成唯一 key - 与原始组件一致
export const generateKey = (id, type) => `${type}_${id}`;

// 获取当前用户ID
export const getCurrentUserId = () => parseInt(sessionStorage.getItem('id') || '0');

// 检查是否是管理员
export const checkIsAdmin = () => sessionStorage.getItem('is_supper') === 'true';

// 判断是否为管理员上传的文件
export const isCreatedByAdmin = (record) => {
  if (!record || !record.created_by) return false;
  return record.created_by.includes('管理员') ||
         record.created_by.includes('admin') ||
         record.created_by.includes('超级管理员');
};

// 判断当前用户是否可以编辑
export const canEditItem = (item, isPublic, isAdmin, currentUserId) => {
  // 私有空间：始终可以编辑
  if (!isPublic) return true;
  // 公共空间：管理员可以编辑
  if (isAdmin) return true;
  // 处理 created_by_id 为 null 的情况
  if (!item.created_by_id) return false;
  return item.created_by_id === currentUserId;
};

// 判断是否为图片文件
export const isImage = (fileType) => {
  if (!fileType) return false;
  const mimeType = fileType.toLowerCase();
  return mimeType.startsWith('image/');
};

// 判断是否为视频文件
export const isVideo = (fileType) => {
  if (!fileType) return false;
  const mimeType = fileType.toLowerCase();
  return mimeType.startsWith('video/');
};

// 格式化文件大小 - 使用公共工具函数
export const formatFileSize = _formatFileSize;

// 格式化日期 - 使用公共工具函数
export const formatDate = _formatDate;

// 将 MIME 类型转换为友好的中文名称
export const getFileTypeLabel = (fileType) => {
  if (!fileType) return '未知类型';
  const mimeType = fileType.toLowerCase();

  const typeMap = {
    'image/jpeg': 'JPEG 图片',
    'image/png': 'PNG 图片',
    'image/gif': 'GIF 图片',
    'image/bmp': 'BMP 图片',
    'image/svg+xml': 'SVG 图片',
    'image/webp': 'WebP 图片',
    'application/pdf': 'PDF 文档',
    'application/msword': 'Word 文档',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word 文档',
    'application/vnd.ms-excel': 'Excel 表格',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel 表格',
    'application/vnd.ms-powerpoint': 'PowerPoint 演示',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint 演示',
    'application/zip': 'ZIP 压缩包',
    'application/x-rar-compressed': 'RAR 压缩包',
    'application/x-7z-compressed': '7Z 压缩包',
    'text/plain': '文本文件',
    'text/html': 'HTML 文件',
    'video/mp4': 'MP4 视频',
    'video/quicktime': 'MOV 视频',
    'video/x-msvideo': 'AVI 视频'
  };

  // 直接匹配
  if (typeMap[fileType]) {
    return typeMap[fileType];
  }

  // 根据前缀匹配
  if (mimeType.startsWith('image/')) {
    const ext = mimeType.split('/')[1]?.toUpperCase();
    return `${ext || ''} 图片`.trim();
  }
  if (mimeType.startsWith('video/')) {
    const ext = mimeType.split('/')[1]?.toUpperCase();
    return `${ext || ''} 视频`.trim();
  }
  if (mimeType.startsWith('audio/')) {
    const ext = mimeType.split('/')[1]?.toUpperCase();
    return `${ext || ''} 音频`.trim();
  }
  if (mimeType.startsWith('text/')) {
    return '文本文件';
  }
  if (mimeType.includes('pdf')) return 'PDF 文档';
  if (mimeType.includes('word') || mimeType.includes('document')) return 'Word 文档';
  if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) return 'Excel 表格';
  if (mimeType.includes('powerpoint') || mimeType.includes('presentation')) return 'PowerPoint 演示';
  if (mimeType.includes('zip') || mimeType.includes('rar') || mimeType.includes('tar') || mimeType.includes('compressed'))
    return '压缩包';

  return '未知类型';
};

// 根据文件类型获取对应图标
export const getFileIcon = (fileName, fileType) => {
  // 从文件名中提取扩展名
  let ext = '';
  if (fileName) {
    const parts = fileName.split('.');
    if (parts.length > 1) {
      ext = parts[parts.length - 1].toLowerCase();
    }
  }

  // 也可以根据 MIME 类型判断
  const mimeType = fileType ? fileType.toLowerCase() : '';

  // 根据扩展名或 MIME 类型判断，返回 emoji
  if (ext === 'pdf' || mimeType.includes('pdf'))
    return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="PDF文档" title="PDF文档">📄</span>;
  if (ext === 'doc' || ext === 'docx' || mimeType.includes('word') || mimeType.includes('document'))
    return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="Word文档" title="Word文档">📝</span>;
  if (ext === 'xls' || ext === 'xlsx' || mimeType.includes('excel') || mimeType.includes('spreadsheet'))
    return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="Excel表格" title="Excel表格">📊</span>;
  if (ext === 'ppt' || ext === 'pptx' || mimeType.includes('powerpoint') || mimeType.includes('presentation'))
    return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="PowerPoint演示" title="PowerPoint演示">📋</span>;
  if (ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif' || ext === 'bmp' || ext === 'svg' ||
      mimeType.includes('image'))
    return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="图片" title="图片">🖼️</span>;
  if (ext === 'zip' || ext === 'rar' || ext === '7z' || ext === 'tar' || ext === 'gz' || mimeType.includes('zip'))
    return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="压缩包" title="压缩包">📦</span>;
  if (ext === 'txt' || ext === 'log' || ext === 'md' || mimeType.includes('text') || mimeType.includes('plain'))
    return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="文本文件" title="文本文件">📃</span>;

  return <span style={{ marginRight: 8, fontSize: 16 }} role="img" aria-label="文件" title="文件">📄</span>;
};

// 获取菜单项图标的符号
export const getMenuIconSymbol = (key) => {
  const iconMap = {
    'open': '📂',
    'download': '⬇️',
    'copy': '📋',
    'cut': '✂️',
    'rename': '✏️',
    'paste': '📎',
    'delete': '🗑️',
    'preview': '👁️',
    'newFolder': '📁'
  };
  return iconMap[key] || '';
};

// 常量配置 - 与原始组件一致
export const CONSTANTS = {
  DOUBLE_CLICK_DELAY: 300,
  BATCH_DELETE_SIZE: 5,
  PAGE_SIZE: 20,
  API_TIMEOUT_MS: 300000,
  API_TIMEOUT_MS_DEV: 60000,
  Z_INDEX_MENU_MASK: 9998,
  Z_INDEX_MENU: 9999
};

// 获取删除请求的超时时间
export const getDeleteTimeout = () => {
  const baseTimeout = CONSTANTS.API_TIMEOUT_MS || 300000;
  const validTimeout = Number.isInteger(baseTimeout) && baseTimeout > 0
    ? baseTimeout
    : 300000;
  return process.env.NODE_ENV === 'production'
    ? validTimeout
    : Math.min(validTimeout, CONSTANTS.API_TIMEOUT_MS_DEV);
};

// 检查文件夹是否是指定文件夹的后代
export const isDescendant = (folderId, ancestorId, folders) => {
  if (folderId === ancestorId) return true;
  let current = folders.find(f => f.id === folderId);
  while (current && current.parent_id !== null) {
    if (current.parent_id === ancestorId) return true;
    const parentId = current.parent_id;
    current = folders.find(f => f.id === parentId);
  }
  return false;
};
