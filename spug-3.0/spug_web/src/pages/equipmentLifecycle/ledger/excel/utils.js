/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel/WPS 维护台账路线工具函数（2026-10-01 自模板导入验证原型
 * prototypeStore 迁出，实现保持不变）。
 *
 * 生成稳定 field_id（UUID v4）：field_id 不由单元格坐标充当，
 * 服务端按原样存储并在发布版本快照中保持稳定。
 */

export function uuidv4() {
  if (window.crypto && window.crypto.getRandomValues) {
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, ch => {
    const rand = Math.random() * 16 | 0;
    return (ch === 'x' ? rand : (rand & 0x3) | 0x8).toString(16);
  });
}
