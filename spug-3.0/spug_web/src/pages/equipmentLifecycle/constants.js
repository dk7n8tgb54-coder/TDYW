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
  // 运行记录（2026-10 第一版）
  RUNTIME_VIEW: 'equipment_lifecycle.runtime_record.view',
  RUNTIME_ADD: 'equipment_lifecycle.runtime_record.add',
  RUNTIME_EDIT: 'equipment_lifecycle.runtime_record.edit',
  RUNTIME_TRIAGE: 'equipment_lifecycle.runtime_record.triage',
  RUNTIME_RESOLVE: 'equipment_lifecycle.runtime_record.resolve',
  RUNTIME_CLOSE: 'equipment_lifecycle.runtime_record.close',
  RUNTIME_CONVERT_FAULT: 'equipment_lifecycle.runtime_record.convert_fault',
  RUNTIME_IMPORTANT: 'equipment_lifecycle.runtime_record.important',
  RUNTIME_LINK: 'equipment_lifecycle.runtime_record.link',
};

// 工单权限码（WO_*）已随「故障维修工单」功能整体删除（2026-09-30）。

// repairing（维修中）已随工单功能删除（2026-09-30）：健康状态只由有效故障驱动
export const HEALTH_STATUS_OPTIONS = [
  {value: 'normal', label: '正常'},
  {value: 'degraded', label: '降级'},
  {value: 'fault', label: '故障'},
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


// 运行记录状态（与后端 SystemRuntimeRecord.STATUS_* 一致）
// 第二版（2026-10）新增：待研判 / 无需跟进
export const RUNTIME_STATUS_OPTIONS = [
  {value: 'recorded', label: '已记录'},
  {value: 'pending_triage', label: '待研判'},
  {value: 'no_follow_up', label: '无需跟进'},
  {value: 'following_up', label: '跟进中'},
  {value: 'resolved', label: '已处理'},
  {value: 'converted_fault', label: '已转故障'},
  {value: 'closed', label: '已关闭'},
];

export const RUNTIME_STATUS_TEXT = RUNTIME_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const RUNTIME_STATUS_COLOR = {
  recorded: 'orange',
  pending_triage: 'gold',
  no_follow_up: 'default',
  following_up: 'geekblue',
  resolved: 'green',
  converted_fault: 'purple',
  closed: 'default',
};

// 运行记录异常类别（与后端 RUNTIME_CATEGORY_* 一致；空串=未选择）
export const RUNTIME_CATEGORY_OPTIONS = [
  {value: 'device', label: '设备异常'},
  {value: 'signal', label: '信号异常'},
  {value: 'link', label: '链路传输'},
  {value: 'power', label: '供电异常'},
  {value: 'environment', label: '机房环境'},
  {value: 'software', label: '软件/数据'},
  {value: 'other', label: '其他'},
];

export const RUNTIME_CATEGORY_TEXT = RUNTIME_CATEGORY_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

// 运行记录影响程度复用故障影响语义（降级/故障/中断；不影响运行时为空）
export const RUNTIME_IMPACT_TEXT = FAULT_IMPACT_TEXT;
export const RUNTIME_IMPACT_COLOR = FAULT_IMPACT_COLOR;

// 运行记录重要程度（与后端 SystemRuntimeRecord.IMPORTANCE_* 一致）
export const RUNTIME_IMPORTANCE_OPTIONS = [
  {value: 'normal', label: '普通'},
  {value: 'important', label: '重要'},
];

export const RUNTIME_IMPORTANCE_TEXT = RUNTIME_IMPORTANCE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});


export const API_PREFIX = '/api/equipment-lifecycle';
