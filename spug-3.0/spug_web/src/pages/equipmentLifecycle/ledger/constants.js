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

export const LEDGER_TYPE = {
  INSPECTION: 'inspection',
  WEEK_MONTH: 'week_month',
  SEASONAL: 'seasonal',
};

export const LEDGER_TYPE_TEXT = {
  inspection: '巡检',
  week_month: '周月维护',
  seasonal: '季维护',
};

export const CYCLE_TEXT = {week: '周', month: '月', season: '季'};

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

export const EXEC_SCOPE_TEXT = {
  all: '周月均执行',
  week_only: '仅每周执行',
  month_only: '仅每月执行',
};

export const INPUT_TYPE_TEXT = {
  text: '数字/文本',
  number: '数值',
  choice: '正常/不正常',
  multi_choice: '多选',
  boolean: '布尔值',
  attachment: '附件',
};

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
