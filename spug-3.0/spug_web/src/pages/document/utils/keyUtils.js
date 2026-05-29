/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */

/**
 * 生成带前缀的唯一key，处理空值/假值场景
 * @param {string|number|null|undefined} id 原始ID（支持0/空字符串等假值）
 * @param {string} prefix 前缀（如folder/file）
 * @returns {string} 带前缀的唯一key
 */
export function generateKey(id, prefix) {
  // 统一处理所有无效ID（null/undefined/''/0）
  const isInvalidId = [null, undefined, '', 0].includes(id);
  if (isInvalidId) {
    // 加长随机串（8位）降低重复概率，格式：前缀-temp-时间戳-随机串
    const randomStr = Math.random().toString(36).slice(2, 10);
    return `${prefix}-temp-${Date.now()}-${randomStr}`;
  }
  // 根节点特殊处理（保持原有命名规范）
  if (id === 'private-root' || id === 'public-root') {
    return id;
  }
  // 正常ID拼接前缀
  return `${prefix}-${id}`;
}

/**
 * 解析key提取原始ID，过滤临时ID、处理异常格式
 * @param {string|null|undefined} key 带前缀的key
 * @returns {string|number|null} 原始ID（临时ID/无效key返回null）
 */
export function parseRawId(key) {
  // 空值兜底
  if (!key) return null;

  // 根节点直接返回
  if (['private-root', 'public-root'].includes(key)) {
    return key;
  }

  // 分割前缀和ID（兼容ID含'-'的场景）
  const separatorIndex = key.indexOf('-');
  if (separatorIndex === -1) return null; // 无分隔符的无效key
  const idPart = key.slice(separatorIndex + 1);

  // 过滤临时ID
  if (idPart.startsWith('temp-')) return null;

  // 转换数字ID（如folder-123 → 123，folder-abc → abc）
  const numId = Number(idPart);
  return isNaN(numId) ? idPart : numId;
}
