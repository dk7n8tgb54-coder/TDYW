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
  // 运行记录（2026-10 第一版；2026-10-07 模块更名 + record_type 扩展）
  RUNTIME_VIEW: 'equipment_lifecycle.runtime_record.view',
  RUNTIME_ADD: 'equipment_lifecycle.runtime_record.add',
  RUNTIME_EDIT: 'equipment_lifecycle.runtime_record.edit',
  RUNTIME_RESOLVE: 'equipment_lifecycle.runtime_record.resolve',
  RUNTIME_CONVERT_FAULT: 'equipment_lifecycle.runtime_record.convert_fault',
  RUNTIME_DEL: 'equipment_lifecycle.runtime_record.del',
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

// 处置类型/处置结果字段已删除（2026-10-05）：原 FAULT_PROGRESS_TYPE_OPTIONS /
// FAULT_PROGRESS_TYPE_TEXT 常量随字段退役一并删除，处置记录仅保留
// 处置时间/处置人/处置措施；排查过程与依据直接作为处置措施文本记录。


// 运行记录状态（与后端 SystemRuntimeRecord.STATUS_* 一致）
// 用户可见状态只有四个（2026-10-05 第四版起研判不再是必经步骤，
// TriageModal 已整体删除）：
// - recorded 已记录：新建成功即已记录，留痕稳定态，可长期保留，不进待办，
//   无需任何研判或关闭操作；顶部动作 = 编辑/开始跟进/转为正式故障；
// - following_up 跟进中：保存首条跟进记录（追加处理进展）后进入，进入待办；
//   跟进人/计划处理时间（跟进计划）已删除（2026-10-06），跟进动作统一为
//   追加处理进展；可新增跟进记录/完成跟进/转为正式故障；
// - completed 已完成：完成跟进后进入，追加处理进展即重新跟进，
//   不提供普通关闭动作；
// - converted_fault 已转故障：后续处置以故障模块为准，只保留查看关联故障
//   （转故障为独立动作，recorded/following_up 均可直接转换，不依赖研判）。
// 历史兼容值 pending_triage/no_follow_up/resolved/closed 已由后端迁移 0007
// 归一为正式状态，前端不再保留别名映射。
// 2026-10-07 record_type 扩展：routine（日常运行）状态恒为 recorded
// （"已记录"），不显示任何异常状态；异常状态仅用于 abnormal（异常事件）。
export const RUNTIME_STATUS_OPTIONS = [
  {value: 'recorded', label: '已记录'},
  {value: 'following_up', label: '跟进中'},
  {value: 'completed', label: '已完成'},
  {value: 'converted_fault', label: '已转故障'},
];

export const RUNTIME_STATUS_TEXT = RUNTIME_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const RUNTIME_STATUS_COLOR = {
  recorded: 'orange',
  following_up: 'geekblue',
  completed: 'green',
  converted_fault: 'purple',
};

// 记录类型（2026-10-07，与后端 SystemRuntimeRecord.record_type 一致）：
// routine 日常运行（不进入异常研判/跟进/转故障流程）/
// abnormal 异常事件（沿用原运行异常记录全部字段与状态机）；
// 历史数据已由迁移 0011 回填为 abnormal，旧请求未传按 abnormal 兼容
export const RUNTIME_RECORD_TYPE_OPTIONS = [
  {value: 'routine', label: '日常运行'},
  {value: 'abnormal', label: '异常事件'},
];

export const RUNTIME_RECORD_TYPE_TEXT = RUNTIME_RECORD_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const RUNTIME_RECORD_TYPE_COLOR = {
  routine: 'blue',
  abnormal: 'volcano',
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

// 运行记录的影响程度/重要程度常量已随字段删除移除（2026-10-06）；
// 故障模块影响语义常量（FAULT_IMPACT_*）继续由故障模块使用。


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
