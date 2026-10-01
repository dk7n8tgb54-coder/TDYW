/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——值班巡检（今日巡检改造）常量与文本映射。
 * 权限码与后端 inspection_views/@auth、role codes.js 保持一致。
 * 业务规则：巡检单唯一范围 = 值班日 + 巡检模板；固定四轮
 * （第四轮 6:30-6:50 发生在次日，归属前一值班日）；不记录实际填写时间；
 * 巡检单只记录结果与现场处理，无转故障入口（历史处置状态只读展示；
 * 转工单已随故障维修工单功能整体删除，2026-09-30）。
 */

export const API_PREFIX = '/api/equipment-lifecycle';

export const PERM_I = {
  VIEW: 'equipment_lifecycle.inspection.view',
  ADD: 'equipment_lifecycle.inspection.add',
  EDIT: 'equipment_lifecycle.inspection.edit',
  SUBMIT: 'equipment_lifecycle.inspection.submit',
  DEL: 'equipment_lifecycle.inspection.del',
  EXPORT: 'equipment_lifecycle.inspection.export',
};

export const PERM_ITPL = {
  VIEW: 'equipment_lifecycle.inspection_template.view',
  ADD: 'equipment_lifecycle.inspection_template.add',
  EDIT: 'equipment_lifecycle.inspection_template.edit',
  DEL: 'equipment_lifecycle.inspection_template.del',
};

// 固定巡检轮次（与后端 INSPECTION_ROUND_CHOICES 一致）
export const INSPECTION_ROUNDS = [
  {value: 'r1', label: '11:00-11:20'},
  {value: 'r2', label: '16:00-16:20'},
  {value: 'r3', label: '22:00-22:20'},
  {value: 'r4', label: '6:30-6:50'},
];

export const ROUND_TEXT = Object.fromEntries(
  INSPECTION_ROUNDS.map(r => [r.value, r.label]));

export const SHEET_STATUS_TEXT = {
  draft: '草稿',
  submitted: '已提交',
  returned: '已退回',
  void: '已作废',
};

export const SHEET_STATUS_COLOR = {
  draft: 'default',
  submitted: 'processing',
  returned: 'warning',
  void: 'default',
};

// 允许编辑明细/值班人员的单据状态（草稿 + 超管退回整改），与后端一致
export const EDITABLE_SHEET_STATUSES = ['draft', 'returned'];

export const RESULT_TEXT = {
  normal: '正常',
  abnormal: '异常',
};

// 与后端 INSPECTION_DEFAULT_CHOICES 对齐
export const NORMAL_VALUE = '正常';
export const ABNORMAL_VALUE = '不正常';
export const NORMAL_ABNORMAL_CHOICES = [NORMAL_VALUE, ABNORMAL_VALUE];

export const DISPOSITION_TEXT = {
  none: '未处置',
  converted_fault: '已转故障',
  target_cancelled: '目标已作废',
};
