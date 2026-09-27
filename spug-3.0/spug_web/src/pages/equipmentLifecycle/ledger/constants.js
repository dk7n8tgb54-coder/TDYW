/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行维护台账（步骤 3.2）常量与文本映射。
 * 权限码与后端 ledger_views/@auth、role codes.js 保持一致。
 */

export const PERM_L = {
  TPL_VIEW: 'equipment_lifecycle.ledger_template.view',
  TPL_ADD: 'equipment_lifecycle.ledger_template.add',
  TPL_EDIT: 'equipment_lifecycle.ledger_template.edit',
  TPL_DEL: 'equipment_lifecycle.ledger_template.del',
  LED_VIEW: 'equipment_lifecycle.ledger.view',
  LED_ADD: 'equipment_lifecycle.ledger.add',
  LED_EDIT: 'equipment_lifecycle.ledger.edit',
  LED_SUBMIT: 'equipment_lifecycle.ledger.submit',
  LED_REVIEW: 'equipment_lifecycle.ledger.review',
  LED_DEL: 'equipment_lifecycle.ledger.del',
  LED_EXPORT: 'equipment_lifecycle.ledger.export',
};

// 台账类型：旧巡检类型 inspection 已删除（2026-09-24），巡检业务走独立巡检单
export const LEDGER_TYPE = {
  WEEK_MONTH: 'week_month',
  SEASONAL: 'seasonal',
};

export const LEDGER_TYPE_TEXT = {
  week_month: '周月维护',
  seasonal: '季维护',
};

// 维护周期（week/month/season）已删除（2026-09-26）：周月维护不再拆分周表/月表，
// 周月维护与季维护仅靠 ledger_type 区分。

export const STATUS_TEXT = {
  draft: '草稿',
  submitted: '已提交',
  returned: '已退回',
  reviewed: '已复核',
  void: '已作废',
};

export const STATUS_COLOR = {
  draft: 'default',
  submitted: 'processing',
  returned: 'warning',
  reviewed: 'success',
  void: 'default',
};

export const RESULT_TEXT = {
  normal: '正常',
  abnormal: '异常',
  not_applicable: '不适用',
  pending_review: '待复核',
};

export const RESULT_COLOR = {
  normal: 'success',
  abnormal: 'error',
  not_applicable: 'default',
  pending_review: 'warning',
};

export const INPUT_TYPE_TEXT = {
  text: '数字/文本',
  number: '数值',
  choice: '正常/不正常',
  multi_choice: '多选',
  boolean: '布尔值',
  attachment: '附件',
};

// ==================== 行对象树（第一阶段：行方向多级 + 平面列项目） ====================
// 行方向最大层级（根为第 1 级；与后端 models.py LEDGER_ROW_MAX_LEVEL 保持一致，
// 本文件是前端唯一权威定义，禁止在组件里散落硬编码）
export const ROW_MAX_LEVEL = 5;

// 行路径分隔符（与后端 ROW_PATH_SEPARATOR 一致）
export const ROW_PATH_SEPARATOR = ' / ';

export const ROW_NODE_TYPE_TEXT = {
  group: '分组',
  repeat_group: '可重复分组',
  check: '检查对象',
};

export const ROW_NODE_TYPE_COLOR = {
  group: 'default',
  repeat_group: 'processing',
  check: 'success',
};

// 列方向第一阶段固定平面结构，模板页固定提示（第二阶段列父子结构另行实施）
export const FLAT_COLUMN_HINT = '检查项目为表格的列，当前为平面结构，暂不支持列分组。';

// 结果含"未填写"（矩阵单元格生成后的初始态，空串）
export const UNSET_RESULT_TEXT = '未填写';

// 矩阵筛选模式
export const MATRIX_FILTER_MODES = [
  {key: 'all', text: '全部'},
  {key: 'abnormal', text: '仅异常'},
  {key: 'unset', text: '仅未填写'},
];

// 模板项目录入类型收敛为两种：正常/不正常、数字/文本；
// 其余类型仅为历史数据保留，新建项目不可再选
export const TEMPLATE_INPUT_TYPE_KEYS = ['choice', 'text'];
// 正常/不正常类型候选项固定，不再开放配置
export const NORMAL_ABNORMAL_CHOICES = ['正常', '不正常'];

export const CREATED_FROM_TEXT = {
  template: '模板生成',
  manual: '临时补录',
};

export const API_PREFIX_L = '/api/equipment-lifecycle';
