/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期（步骤二）常量与文本映射。
 * 权限码与后端 @auth、role codes.js 保持一致。
 */

export const PERM = {
  SYS_VIEW: 'equipment_lifecycle.system.view',
  SYS_ADD: 'equipment_lifecycle.system.add',
  SYS_EDIT: 'equipment_lifecycle.system.edit',
  SYS_DEL: 'equipment_lifecycle.system.del',
  SYS_DEACTIVATE: 'equipment_lifecycle.system.deactivate',
  SYS_EXPORT: 'equipment_lifecycle.system.export',
  FAULT_VIEW: 'equipment_lifecycle.fault.view',
  FAULT_ADD: 'equipment_lifecycle.fault.add',
  FAULT_EDIT: 'equipment_lifecycle.fault.edit',
  FAULT_HANDLE: 'equipment_lifecycle.fault.handle',
  FAULT_RECOVER: 'equipment_lifecycle.fault.recover',
  FAULT_CLOSE: 'equipment_lifecycle.fault.close',
  FAULT_DEL: 'equipment_lifecycle.fault.del',
  FAULT_EXPORT: 'equipment_lifecycle.fault.export',
  LEDGER_HANDLE_EXCEPTION: 'equipment_lifecycle.ledger.handle_exception',
  WO_VIEW: 'equipment_lifecycle.work_order.view',
  WO_ADD: 'equipment_lifecycle.work_order.add',
  WO_EDIT: 'equipment_lifecycle.work_order.edit',
  WO_DISPATCH: 'equipment_lifecycle.work_order.dispatch',
  WO_ACCEPT: 'equipment_lifecycle.work_order.accept',
  WO_EXECUTE: 'equipment_lifecycle.work_order.execute',
  WO_REVIEW: 'equipment_lifecycle.work_order.review',
  WO_CLOSE: 'equipment_lifecycle.work_order.close',
  WO_DEL: 'equipment_lifecycle.work_order.del',
  WO_EXPORT: 'equipment_lifecycle.work_order.export',
};

export const HEALTH_STATUS_OPTIONS = [
  {value: 'normal', label: '正常'},
  {value: 'degraded', label: '降级'},
  {value: 'fault', label: '故障'},
  {value: 'repairing', label: '维修中'},
  {value: 'interrupted', label: '中断'},
  {value: 'unknown', label: '未知'},
];

export const HEALTH_STATUS_TEXT = HEALTH_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const HEALTH_STATUS_COLOR = {
  normal: 'green',
  degraded: 'orange',
  fault: 'red',
  repairing: 'geekblue',
  interrupted: 'red',
  unknown: 'default',
};

export const FAULT_STATUS_OPTIONS = [
  {value: 'pending', label: '待处置'},
  {value: 'handling', label: '处置中'},
  {value: 'recovered', label: '已恢复'},
  {value: 'closed', label: '已关闭'},
  {value: 'cancelled', label: '已作废'},
];

export const FAULT_STATUS_TEXT = FAULT_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const FAULT_STATUS_COLOR = {
  pending: 'orange',
  handling: 'geekblue',
  recovered: 'green',
  closed: 'default',
  cancelled: 'default',
};

export const FAULT_IMPACT_OPTIONS = [
  {value: 'degraded', label: '降级'},
  {value: 'fault', label: '故障'},
  {value: 'interrupted', label: '中断'},
];

export const FAULT_IMPACT_TEXT = FAULT_IMPACT_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const FAULT_IMPACT_COLOR = {
  degraded: 'orange',
  fault: 'red',
  interrupted: 'red',
};

export const FAULT_LEVEL_OPTIONS = [
  {value: 'minor', label: '一般'},
  {value: 'major', label: '严重'},
  {value: 'critical', label: '重大'},
];

export const FAULT_LEVEL_TEXT = FAULT_LEVEL_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const FAULT_DISCOVERY_OPTIONS = [
  {value: 'patrol', label: '巡检发现'},
  {value: 'alarm', label: '告警发现'},
  {value: 'report', label: '人工报告'},
  {value: 'other', label: '其他'},
];

export const FAULT_DISCOVERY_TEXT = FAULT_DISCOVERY_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

// 故障处理进展类型（选填，与后端 SystemFaultHandlingRecord.PROGRESS_TYPE_CHOICES 一致）
export const FAULT_PROGRESS_TYPE_OPTIONS = [
  {value: 'check', label: '检查'},
  {value: 'self_fix', label: '本方处理'},
  {value: 'to_vendor', label: '送厂'},
  {value: 'vendor_feedback', label: '厂家反馈'},
  {value: 'return', label: '返还'},
  {value: 'test', label: '测试'},
  {value: 'watch', label: '持续观察'},
  {value: 'other', label: '其他'},
];

export const FAULT_PROGRESS_TYPE_TEXT = FAULT_PROGRESS_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});


export const API_PREFIX = '/api/equipment-lifecycle';
