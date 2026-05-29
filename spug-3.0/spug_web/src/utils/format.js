/**
 * 格式化工具函数
 * @module utils/format
 * @description 提供通用的格式化函数，用于资料库模块
 */

/**
 * 格式化文件大小
 * @param {number} bytes - 字节数
 * @returns {string} 格式化后的文件大小
 * @example
 * formatFileSize(1024) // "1.00 KB"
 * formatFileSize(0) // "0 B"
 * formatFileSize(null) // "0 B"
 */
export function formatFileSize(bytes) {
  // 边界情况处理
  if (bytes === null || bytes === undefined || bytes === 0) {
    return '0 B';
  }
  // 处理负数和非数字输入
  if (typeof bytes !== 'number' || isNaN(bytes)) {
    return '-';
  }
  if (bytes < 0) {
    return '-';
  }
  // 处理极大数值（超过Number.MAX_SAFE_INTEGER）
  if (!isFinite(bytes)) {
    return '∞';
  }

  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }

  // 对于小于1KB的文件，显示整数字节
  if (unitIndex === 0) {
    return Math.round(size) + ' ' + units[unitIndex];
  }

  // 对于较大的文件，保留2位小数
  return size.toFixed(2) + ' ' + units[unitIndex];
}

/**
 * 格式化文件大小（简化版）
 * @param {number} bytes - 字节数
 * @returns {string} 格式化后的文件大小
 * @description 用于传输列表等需要简洁显示的场景
 */
export function formatSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const index = Math.min(i, sizes.length - 1);
  return parseFloat((bytes / Math.pow(k, index)).toFixed(2)) + ' ' + sizes[index];
}

/**
 * 格式化传输速度
 * @param {number} bytesPerSecond - 每秒字节数
 * @returns {string} 格式化后的速度
 * @example
 * formatSpeed(1024000) // "1000.00 KB/s"
 */
export function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond || bytesPerSecond <= 0) return '';
  return formatSize(bytesPerSecond) + '/s';
}

/**
 * 格式化日期
 * @param {string|Date} dateStr - 日期字符串或Date对象
 * @param {boolean} withTime - 是否包含时间
 * @returns {string} 格式化后的日期
 * @example
 * formatDate('2024-01-01') // "2024年1月1日"
 * formatDate('2024-01-01 10:30:00', true) // "2024年1月1日 10:30:00"
 */
export function formatDate(dateStr, withTime = false) {
  if (!dateStr) return '-';

  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return '-';

  const options = {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  };

  if (withTime) {
    options.hour = '2-digit';
    options.minute = '2-digit';
    options.second = '2-digit';
  }

  return date.toLocaleString('zh-CN', options);
}

/**
 * 格式化相对时间
 * @param {string|Date} dateStr - 日期字符串或Date对象
 * @returns {string} 相对时间描述
 * @example
 * formatRelativeTime(new Date()) // "刚刚"
 * formatRelativeTime(Date.now() - 60000) // "1分钟前"
 */
export function formatRelativeTime(dateStr) {
  if (!dateStr) return '-';

  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return '-';

  const now = new Date();
  const diff = now - date;
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (seconds < 60) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 30) return `${days}天前`;

  return formatDate(dateStr);
}

/**
 * 格式化百分比
 * @param {number} value - 0-100之间的数值
 * @param {number} decimals - 小数位数，默认1
 * @returns {string} 格式化后的百分比
 */
export function formatPercent(value, decimals = 1) {
  if (typeof value !== 'number' || isNaN(value)) return '-';
  if (value < 0) return '0%';
  if (value > 100) return '100%';
  return value.toFixed(decimals) + '%';
}

/**
 * 格式化数字（带千分位分隔符）
 * @param {number} num - 数字
 * @returns {string} 格式化后的数字
 * @example
 * formatNumber(1000000) // "1,000,000"
 */
export function formatNumber(num) {
  if (typeof num !== 'number' || isNaN(num)) return '-';
  return num.toLocaleString('zh-CN');
}
