/**
 * 部门日检查单模块公共常量
 * P3-1 修复：抽取重复定义的 STATUS_MAP 为公共常量
 */

export const STATUS_MAP = {
  'NORMAL': { label: '√', color: '#52c41a', bgColor: '#f6ffed', text: '正常' },
  'ABNORMAL': { label: '×', color: '#ff4d4f', bgColor: '#fff1f0', text: '异常' },
  'UNCHECKED': { label: '—', color: '#d9d9d9', bgColor: '#fafafa', text: '未检查' }
};
