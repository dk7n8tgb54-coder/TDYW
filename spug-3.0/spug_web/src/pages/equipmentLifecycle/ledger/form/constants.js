/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单台账路线常量（2026-10-21，与后端 form_template_manage 保持一致）：
 * 字段类型枚举、分组种类、模板路线标记与展示文本。
 * 权限码沿用 ledger_template.*（模板管理）与 ledger.*（台账），见 PERM_L。
 */

// 分组种类（后端 GROUP_KIND_*）
export const GROUP_KIND = {
  FIELDS: 'fields',   // 普通分组
  REPEAT: 'repeat',   // 可重复明细组
  MATRIX: 'matrix',   // 检查矩阵
};

/**
 * 分组种类展示文本（2026-10-23 按设计方案 2.3 统一词汇）。
 * P2 起编辑器、填写页渲染器（FormFillRenderer 分组角标）与 PDF 样张
 * （后端 _KIND_TAG）共用同一套词汇，保证"看到的就是下载的"。
 */
export const GROUP_KIND_TEXT = {
  fields: '固定填写项',
  repeat: '可重复明细',
  matrix: '检查对比表',
};

// 字段类型（后端 FIELD_*）
export const FIELD_TYPE_TEXT = {
  text: '单行文本',
  textarea: '多行文本',
  number: '数字',
  date: '日期',
  choice: '单选',
  normal_abnormal: '正常/异常',
};

// 矩阵行支持的类型（多行文本/日期不适合横向比较，不开放）
export const MATRIX_ROW_TYPE_VALUES = ['text', 'number', 'choice', 'normal_abnormal'];

export const FIELD_TYPE_OPTIONS = Object.keys(FIELD_TYPE_TEXT).map(value => ({
  value, label: FIELD_TYPE_TEXT[value],
}));

export const MATRIX_ROW_TYPE_OPTIONS = MATRIX_ROW_TYPE_VALUES.map(value => ({
  value, label: FIELD_TYPE_TEXT[value],
}));

// normal_abnormal 取值与展示
export const NORMAL_ABNORMAL_OPTIONS = [
  {value: 'normal', label: '正常'},
  {value: 'abnormal', label: '异常'},
];

// 异常说明键后缀（与后端 DESC_SUFFIX 一致）
export const DESC_SUFFIX = '__desc';

/**
 * 结构协议版本（2026-10-23 P2 升为 2，与后端 PROTOCOL_VERSION 一致）：
 * 新增可选键 textarea.rows（2~8，默认 2）、number.min/max/precision
 * （0~3 位小数，可空）、normal_abnormal.require_desc_when_abnormal
 * （异常时说明必填，默认否）。加载历史 v1 草稿时编辑器本地升级为 v2，
 * 以"未保存修改"呈现，须显式保存后才可发布；不支持的未来版本由后端
 * fail-closed 拒绝（前端不做第二套判定）。
 */
export const PROTOCOL_VERSION = 2;

// 多行文本行数（textarea.rows）取值范围与缺省
export const TEXTAREA_ROWS_MIN = 2;
export const TEXTAREA_ROWS_MAX = 8;
export const TEXTAREA_ROWS_DEFAULT = 2;

// 数字小数位（number.precision）上限；null=不限
export const NUMBER_PRECISION_MAX = 3;

// 模板路线标记（生成预览条目 template_kind）
export const TEMPLATE_KIND_TEXT = {
  excel: 'Excel模板',
  form: '数字表单',
};

// 统一列表来源（source_type）展示文本
export const SOURCE_TYPE_TEXT = {
  manual: '临时补录',
  excel: 'Excel模板',
  form: '数字表单',
};

// 模板四态（与 Excel 模板同口径）
export const TEMPLATE_STATUS_TEXT = {
  draft: '草稿',
  published: '已发布',
  used: '使用中',
  deleted: '已停用',
};

/**
 * 结构 id 生成：前缀 + 8 位随机小写字母数字（g/f/c/r）。
 * 满足后端规则：^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$ 且不含双下划线。
 */
export function genId(prefix) {
  let tail = '';
  while (tail.length < 8) {
    tail += Math.random().toString(36).slice(2);
  }
  return `${prefix}${tail.slice(0, 8).replace(/[^a-z0-9]/g, '0')}`;
}
