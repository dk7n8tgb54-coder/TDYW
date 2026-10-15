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
  LEDGER_HANDLE_EXCEPTION: 'equipment_lifecycle.ledger.handle_exception',
  // 运行处置记录（2026-10-11 合并改造：原 fault.* 与 runtime_record.*
  // 权限域合并换发为 operation_record.*，由迁移 0013 清洗角色权限）
  OP_VIEW: 'equipment_lifecycle.operation_record.view',
  OP_ADD: 'equipment_lifecycle.operation_record.add',
  OP_ADD_FAULT: 'equipment_lifecycle.operation_record.add_fault',
  OP_EDIT: 'equipment_lifecycle.operation_record.edit',
  // OP_PROGRESS：进展追加端点权限（详情顶部"添加跟进/补充/处置记录"按钮
  // 与后端 @auth 一致；2026-10-14 起成为新增进展的按钮级控制）
  OP_PROGRESS: 'equipment_lifecycle.operation_record.progress',
  OP_COMPLETE: 'equipment_lifecycle.operation_record.complete',
  OP_IDENTIFY_FAULT: 'equipment_lifecycle.operation_record.identify_fault',
  OP_RECOVER: 'equipment_lifecycle.operation_record.recover',
  OP_CLOSE: 'equipment_lifecycle.operation_record.close',
  OP_CANCEL: 'equipment_lifecycle.operation_record.cancel',
  OP_DEL: 'equipment_lifecycle.operation_record.del',
  OP_EXPORT: 'equipment_lifecycle.operation_record.export',
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

// ==================== 运行处置记录统一状态/类型（2026-10-11 合并改造） ====================
// 统一六状态：一般记录恒为已记录；异常事件 已记录→跟进中→已完成；
// 设备故障 处置中→已关闭 / 处置中→已撤销（错误/重复登记受控撤销）。
// 已撤销使用虚线边框的中性灰样式（RecordStatusTag），与进行态明显区分。
export const RECORD_STATUS_OPTIONS = [
  {value: 'recorded', label: '已记录'},
  {value: 'following_up', label: '跟进中'},
  {value: 'completed', label: '已完成'},
  {value: 'handling', label: '处置中'},
  {value: 'closed', label: '已关闭'},
  {value: 'cancelled', label: '已撤销'},
];

export const RECORD_STATUS_TEXT = RECORD_STATUS_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const RECORD_STATUS_COLOR = {
  recorded: 'orange',
  following_up: 'geekblue',
  completed: 'green',
  handling: 'volcano',
  closed: 'default',
  cancelled: 'default',
};

// 记录类型（2026-10-12 显示名调整，与后端 SystemOperationRecord.record_type 一致）：
// routine 一般记录 / abnormal 异常事件 / fault 设备故障。
// 异常事件可在原记录上认定为设备故障（类型原地变更，不创建第二张单）。
export const RECORD_TYPE_OPTIONS = [
  {value: 'routine', label: '一般记录'},
  {value: 'abnormal', label: '异常事件'},
  {value: 'fault', label: '设备故障'},
];

export const RECORD_TYPE_TEXT = RECORD_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const RECORD_TYPE_COLOR = {
  routine: 'blue',
  abnormal: 'gold',
  fault: 'red',
};

// 三类记录的用途说明（新增表单选项说明/详情下一步提示共用一套口径，
// 与后端 operation_models.record_type 帮助文本一致）：
// - 一般记录不进入故障流程；- 异常事件可跟进、可认定故障；
// - 设备故障直接登记后进入处置中，须完成恢复确认并结案
export const RECORD_TYPE_HINTS = {
  routine: '常规作业与运行情况留痕：不进入故障流程，不影响系统健康状态，可随时补充记录。',
  abnormal: '需要跟进确认的异常或疑问：先记录再跟进，必要时可在详情中认定为设备故障。',
  fault: '设备故障登记（需 add_fault 授权）：登记即进入"处置中"，恢复后须确认恢复并结案。',
};

// 设备故障影响程度（设备故障专用字段；不影响运行时无程度）
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

// 异常类别（2026-10-11 合并改造，与后端 RECORD_CATEGORY_* 一致；空串=未选择；
// 仅一般记录与异常事件使用，设备故障不适用）
export const RECORD_CATEGORY_OPTIONS = [
  {value: 'device', label: '设备异常'},
  {value: 'signal', label: '信号异常'},
  {value: 'link', label: '链路传输'},
  {value: 'power', label: '供电异常'},
  {value: 'environment', label: '机房环境'},
  {value: 'software', label: '软件/数据'},
  {value: 'other', label: '其他'},
];

export const RECORD_CATEGORY_TEXT = RECORD_CATEGORY_OPTIONS.reduce((acc, item) => {
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
