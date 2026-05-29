/**
 * 工具函数统一入口
 * @module utils
 * @description 资料库模块的公共工具函数
 */

// 格式化工具
export {
  formatFileSize,
  formatSize,
  formatSpeed,
  formatDate,
  formatRelativeTime,
  formatPercent,
  formatNumber,
} from './format';

// 文件类型判断工具
export {
  isImage,
  isVideo,
  getFileType,
  getFileTypeLabel,
  getFileIcon,
} from './fileType';

// 通用工具
export {
  debounce,
  throttle,
  generateUUID,
  deepClone,
} from './common';
