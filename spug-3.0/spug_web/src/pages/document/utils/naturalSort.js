/**
 * 自然排序工具（数字按数值比较："文件2" < "文件11"）
 * 与 Windows 资源管理器一致；供文件列表排序、文件夹树、树选择器共用，
 * 保证各视图同名条目顺序一致。
 */

/**
 * 自然排序比较两个值（zh-CN locale）
 * @param {*} a - 值A（null/undefined 视为空串）
 * @param {*} b - 值B
 * @returns {number} 比较结果
 */
export const naturalCompare = (a, b) => {
  const sa = a == null ? '' : String(a);
  const sb = b == null ? '' : String(b);
  return sa.localeCompare(sb, 'zh-CN', { numeric: true });
};

/**
 * 按名称字段对文件夹/文件数组自然排序（返回新数组，不修改原数组）
 * @param {Array} items - 待排序数组
 * @param {string} nameKey - 名称字段（默认 'name'）
 * @returns {Array} 排序后的新数组
 */
export const sortByName = (items, nameKey = 'name') =>
  [...(items || [])].sort((x, y) => naturalCompare(x[nameKey], y[nameKey]));
