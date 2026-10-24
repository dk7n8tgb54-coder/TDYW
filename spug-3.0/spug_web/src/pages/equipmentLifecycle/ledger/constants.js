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

// 台账状态（2026-10-16 流程简化）：草稿/已完成/已作废 三状态
export const STATUS_TEXT = {
  draft: '草稿',
  completed: '已完成',
  void: '已作废',
};

export const STATUS_COLOR = {
  draft: 'default',
  completed: 'success',
  void: 'default',
};

// 状态筛选项（2026-10-17）：默认视图（未选择状态）不展示已作废，历史
// 状态台账仍在默认列表中展示；"已作废"选项主动查看；"全部"（'all'，筛选
// 专用值、非台账状态）明确包含已作废。与后端 apply_ledger_status_filter 口径一致
export const STATUS_FILTER_ALL = 'all';

export const STATUS_FILTER_OPTIONS = [
  {value: STATUS_FILTER_ALL, label: '全部'},
  {value: 'draft', label: STATUS_TEXT.draft},
  {value: 'completed', label: STATUS_TEXT.completed},
  {value: 'void', label: STATUS_TEXT.void},
];

// 可删除状态：草稿（已完成/已作废不可删除，与后端一致）
export const DELETABLE_STATUS = ['draft'];

// ======================================================================
// "批量导出 PDF"（2026-10-21）：状态范围口径与后端一致
// - ''（默认）：仅已完成（不含草稿/已作废）；
// - 'all'：全部（含草稿、已作废）；其余值为精确单状态。
// 模板候选数据（GET /ledgers/export-pdf/）的 counts/versions 按"状态 → 数量"
// 下发，以下纯函数负责计算所选范围下的可导出数量与涉及版本。
// ======================================================================

export const EXPORT_SCOPE_STATUSES = {
  '': ['completed'],
  all: ['completed', 'draft', 'void'],
  draft: ['draft'],
  completed: ['completed'],
  void: ['void'],
};

export const EXPORT_STATUS_OPTIONS = [
  {value: '', label: '已完成（默认，不含草稿/已作废）'},
  {value: 'all', label: '全部（含草稿、已作废）'},
  {value: 'draft', label: '草稿'},
  {value: 'void', label: '已作废'},
];

/** 模板在所选状态范围下的可导出台账数量。 */
export function exportableCountOf(template, status) {
  if (!template) return 0;
  const statuses = EXPORT_SCOPE_STATUSES[status] || EXPORT_SCOPE_STATUSES[''];
  return statuses.reduce((sum, key) => sum + ((template.counts || {})[key] || 0), 0);
}

/** 模板在所选状态范围下的涉及版本（[{version_no, count}]，版本号升序）。 */
export function versionsUnderScope(template, status) {
  if (!template) return [];
  const statuses = EXPORT_SCOPE_STATUSES[status] || EXPORT_SCOPE_STATUSES[''];
  return Object.keys(template.versions || {})
    .map(versionNo => ({
      version_no: parseInt(versionNo, 10),
      count: statuses.reduce(
        (sum, key) => sum + ((template.versions[versionNo] || {})[key] || 0), 0),
    }))
    .filter(item => item.count > 0)
    .sort((a, b) => a.version_no - b.version_no);
}

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
  form_template: '数字表单',
};

export const API_PREFIX_L = '/api/equipment-lifecycle';
