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

export const CREATED_FROM_TEXT = {
  manual: '临时补录',
  excel_template: 'Excel模板',
};

// ==================== 统一列表来源（2026-10 Excel 台账接入正式列表） ====================
// 后端 /ledgers/ 返回 source_type（由 created_from 派生），前端按此渲染来源标签；
// Excel 来源记录点击详情进入 ExcelLedgerDetail，手工补录走既有明细详情。
// 旧可视化模板来源（visual）已随路线删除（2026-10）。
export const SOURCE_TYPE_TEXT = {
  excel: 'Excel模板',
  manual: '临时补录',
};

export const SOURCE_TYPE_COLOR = {
  excel: 'green',
  manual: 'default',
};

export const API_PREFIX_L = '/api/equipment-lifecycle';
