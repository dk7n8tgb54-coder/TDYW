/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行维护台账（步骤 3.2）常量与文本映射。
 * 权限码与后端 ledger_views/@auth、role codes.js 保持一致。
 * 旧可视化模板路线常量（ROW_* / MATRIX_* / TEMPLATE_INPUT_TYPE_* 等）
 * 已随路线删除（2026-10）。
 */

export const PERM_L = {
  // Excel 模板管理沿用 ledger_template.* 权限码（后端 excel_template_views 独立校验）
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

// 台账类型 → 路由路径（来源/目标跳转用；2026-09-30 自 workOrder/constants 迁入，
// 工单功能已删除；旧巡检类型已删除，legacy 快照来源在详情页仅展示文本，不做跳转）
export const LEDGER_TYPE_PATH = {
  week_month: '/el/week-month-ledgers',
  seasonal: '/el/seasonal-ledgers',
};

// 台账状态（2026-10-16 流程简化）：新流程只用 草稿/已完成/已作废 三状态；
// submitted/returned/reviewed 为旧流程历史状态，仅存量台账展示用
export const STATUS_TEXT = {
  draft: '草稿',
  completed: '已完成',
  void: '已作废',
  submitted: '已提交',
  returned: '已退回',
  reviewed: '已复核',
};

export const STATUS_COLOR = {
  draft: 'default',
  completed: 'success',
  void: 'default',
  submitted: 'processing',
  returned: 'warning',
  reviewed: 'success',
};

// 状态筛选项：仅新流程三状态（历史状态台账仍在默认列表中展示）
export const STATUS_FILTER_OPTIONS = ['draft', 'completed', 'void'];

// 可删除状态：草稿与旧流程历史状态（已完成/已作废不可删除，与后端一致）
export const DELETABLE_STATUS = ['draft', 'submitted', 'returned', 'reviewed'];

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

export const CREATED_FROM_TEXT = {
  manual: '临时补录',
  excel_template: 'Excel模板',
};

export const API_PREFIX_L = '/api/equipment-lifecycle';
