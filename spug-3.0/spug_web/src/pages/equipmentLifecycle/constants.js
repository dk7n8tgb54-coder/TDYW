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
  // 系统配置（2026-10）：只在系统详情"配置"页签内使用，不设独立菜单
  CONFIG_VIEW: 'equipment_lifecycle.config.view',
  CONFIG_ADD: 'equipment_lifecycle.config.add',
  CONFIG_EDIT: 'equipment_lifecycle.config.edit',
  CONFIG_APPLY: 'equipment_lifecycle.config.apply',
  CONFIG_VERIFY: 'equipment_lifecycle.config.verify',
  CONFIG_ROLLBACK: 'equipment_lifecycle.config.rollback',
  CONFIG_TEMPLATE: 'equipment_lifecycle.config.template',
  CONFIG_ATTACHMENT: 'equipment_lifecycle.config.attachment',
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

// 2026-10 流程简化：新建即处置中，确认恢复并结案后进入已关闭终态；
// 旧 pending/recovered 过渡态已删除（模块未上线，无历史包袱）。
// 2026-10-03 撤销登记改版：后端状态值 cancelled 保持不变（历史数据兼容），
// 用户可见文案统一为"已撤销"——表示这条登记本身不再作为有效故障
// （错误/重复/误报登记被撤销），历史记录保留可追溯；
// 与"已关闭"（真实故障已恢复并完成结案）语义区分。
export const FAULT_STATUS_OPTIONS = [
  {value: 'handling', label: '处置中'},
  {value: 'closed', label: '已关闭'},
  {value: 'cancelled', label: '已撤销'},
];

export const FAULT_STATUS_TEXT = FAULT_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

// 已撤销使用虚线边框的中性灰样式（renderCancelledStatusTag），与处置中
// （geekblue 实色）和已关闭（灰实线）明显区分但克制，不使用红/橙等告警色
export const FAULT_STATUS_COLOR = {
  handling: 'geekblue',
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
// 故障定位（fault_locate，2026-10）：记录原因判断的依据与过程，
// 是形成"原因分析"结论的过程记录，不替代原因分析结论本身
export const FAULT_PROGRESS_TYPE_OPTIONS = [
  {value: 'check', label: '检查'},
  {value: 'fault_locate', label: '故障定位'},
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
// 第二版（2026-10）新增：无需跟进；待研判自 2026-10-04 起为历史兼容状态
// （新流程新建即"已记录"，研判直接出结论，不再产生待研判）。
// 研判为可选动作：已记录可留痕保留或直接关闭，不要求先研判。
export const RUNTIME_STATUS_OPTIONS = [
  {value: 'recorded', label: '已记录'},
  {value: 'pending_triage', label: '待研判（历史）'},
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

// ==================== 系统配置（2026-10，与后端 config_models 一致） ====================

// 配置变更状态
export const CONFIG_CHANGE_STATUS_OPTIONS = [
  {value: 'draft', label: '草稿'},
  {value: 'applied', label: '已生效'},
  {value: 'verified', label: '已验证'},
  {value: 'rolled_back', label: '已回退'},
  {value: 'cancelled', label: '已取消'},
];

export const CONFIG_CHANGE_STATUS_TEXT = CONFIG_CHANGE_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const CONFIG_CHANGE_STATUS_COLOR = {
  draft: 'orange',
  applied: 'geekblue',
  verified: 'green',
  rolled_back: 'default',
  cancelled: 'default',
};

// 参数数据类型
export const PARAM_TYPE_OPTIONS = [
  {value: 'text', label: '文本'},
  {value: 'number', label: '数字'},
  {value: 'bool', label: '布尔'},
  {value: 'date', label: '日期'},
  {value: 'choice', label: '枚举'},
];

export const PARAM_TYPE_TEXT = PARAM_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

// 验证状态
export const CONFIG_VERIFY_STATUS_TEXT = {
  '': '未验证',
  passed: '验证通过',
  failed: '验证不通过',
};

export const CONFIG_VERIFY_STATUS_COLOR = {
  '': 'default',
  passed: 'green',
  failed: 'red',
};
