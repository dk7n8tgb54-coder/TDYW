/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——工单管理（步骤 3.3）常量与文本映射。
 * 权限码与后端 @auth、role codes.js 保持一致；状态流转以后端状态机为准。
 */

export const WO_PERM = {
  VIEW: 'equipment_lifecycle.work_order.view',
  ADD: 'equipment_lifecycle.work_order.add',
  EDIT: 'equipment_lifecycle.work_order.edit',
  DISPATCH: 'equipment_lifecycle.work_order.dispatch',
  ACCEPT: 'equipment_lifecycle.work_order.accept',
  EXECUTE: 'equipment_lifecycle.work_order.execute',
  REVIEW: 'equipment_lifecycle.work_order.review',
  CLOSE: 'equipment_lifecycle.work_order.close',
  DEL: 'equipment_lifecycle.work_order.del',
  EXPORT: 'equipment_lifecycle.work_order.export',
  LEDGER_HANDLE: 'equipment_lifecycle.ledger.handle_exception',
};

export const WORK_TYPE_OPTIONS = [
  {value: 'repair', label: '故障维修'},
  {value: 'special_maintenance', label: '专项维护'},
  {value: 'tech_reform', label: '技术改造'},
  {value: 'config_change', label: '配置变更'},
  {value: 'field_test', label: '现场测试'},
  {value: 'calibration', label: '校准'},
];

export const WORK_TYPE_TEXT = WORK_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const WO_STATUS_OPTIONS = [
  {value: 'pending_dispatch', label: '待派发'},
  {value: 'pending_accept', label: '待接单'},
  {value: 'executing', label: '执行中'},
  {value: 'pending_review', label: '待复核'},
  {value: 'completed', label: '已完成'},
  {value: 'closed', label: '已关闭'},
  {value: 'cancelled', label: '已取消'},
];

export const WO_STATUS_TEXT = WO_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const WO_STATUS_COLOR = {
  pending_dispatch: 'orange',
  pending_accept: 'gold',
  executing: 'geekblue',
  pending_review: 'purple',
  completed: 'green',
  closed: 'default',
  cancelled: 'default',
};

export const PRIORITY_OPTIONS = [
  {value: 'low', label: '较低'},
  {value: 'normal', label: '一般'},
  {value: 'high', label: '高'},
  {value: 'urgent', label: '紧急'},
];

export const PRIORITY_TEXT = PRIORITY_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const PRIORITY_COLOR = {
  low: 'default',
  normal: 'blue',
  high: 'orange',
  urgent: 'red',
};

export const WO_SOURCE_TEXT = {
  manual: '人工创建',
  fault: '来源故障',
  ledger_item: '来源台账异常',
};

export const DISPOSITION_TEXT = {
  none: '未处置',
  converted_fault: '已转故障',
  converted_work_order: '已转工单',
  target_cancelled: '处置目标已取消或作废',
};

export const DISPOSITION_COLOR = {
  none: 'default',
  converted_fault: 'red',
  converted_work_order: 'geekblue',
  target_cancelled: 'orange',
};

// 台账类型 → 路由路径（来源/目标跳转用）
export const LEDGER_TYPE_PATH = {
  inspection: '/el/inspection-ledgers',
  week_month: '/el/week-month-ledgers',
  seasonal: '/el/seasonal-ledgers',
};

export const API_PREFIX = '/api/equipment-lifecycle';
