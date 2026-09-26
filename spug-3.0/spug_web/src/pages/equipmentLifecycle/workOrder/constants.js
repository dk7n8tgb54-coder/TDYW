/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——工单管理（步骤 3.3，单账号协同流程）常量与文本映射。
 * 权限码与后端 @auth、role codes.js 保持一致；状态流转以后端状态机为准。
 * 单账号协同流程（2026-09）：新工单创建即执行中，派发/接单/复核环节已下线；
 * 待派发/待接单/待复核仅为历史兼容状态，不在筛选选项中提供，但历史数据仍可显示。
 */

export const WO_PERM = {
  VIEW: 'equipment_lifecycle.work_order.view',
  ADD: 'equipment_lifecycle.work_order.add',
  EDIT: 'equipment_lifecycle.work_order.edit',
  EXECUTE: 'equipment_lifecycle.work_order.execute',
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

// 顶层工单类型收敛（2026-09）：新建/编辑只允许以下两种类型；
// 技术改造统一由"系统升级管理"承载（不在工单中登记，也不自动建单），
// 配置变更/现场测试/校准并入专项维护的"维护分类"（见 MAINTENANCE_SUBTYPE_OPTIONS）。
// WORK_TYPE_OPTIONS 保留全部历史类型，仅供列表筛选与历史工单展示。
export const WORK_TYPE_CREATION_OPTIONS = [
  {value: 'repair', label: '故障维修'},
  {value: 'special_maintenance', label: '专项维护'},
];

// 已下线顶层类型：仅用于编辑历史工单时回显原值（禁用不可选）与文案提示，
// 新建/编辑均不可再选择；后端创建/编辑接口独立拒绝。
export const RETIRED_WORK_TYPE_TEXT = {
  tech_reform: '技术改造',
  config_change: '配置变更',
  field_test: '现场测试',
  calibration: '校准',
};

// 类型边界提示（表单 extra 文案，与后端拒绝文案语义一致）
export const WORK_TYPE_HINT =
  '技术改造请在「系统升级管理」中登记；配置变更/现场测试/校准作为专项维护的维护分类';

// 专项维护二级分类（维护分类）：默认"一般维护"；配置变更仅作为维护分类
// 记录，不直接等同于修改系统档案（系统档案只维护当前有效主数据）
export const MAINTENANCE_SUBTYPE_DEFAULT = 'general';

export const MAINTENANCE_SUBTYPE_OPTIONS = [
  {value: 'general', label: '一般维护'},
  {value: 'config_change', label: '配置变更'},
  {value: 'field_test', label: '现场测试'},
  {value: 'calibration', label: '校准'},
  {value: 'temporary_maintenance', label: '临时维护'},
];

export const MAINTENANCE_SUBTYPE_TEXT = MAINTENANCE_SUBTYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

// 状态筛选选项：仅新流程状态（历史兼容状态不作为筛选选项）
export const WO_STATUS_OPTIONS = [
  {value: 'executing', label: '执行中'},
  {value: 'completed', label: '已完成'},
  {value: 'closed', label: '已关闭'},
  {value: 'cancelled', label: '已取消'},
];

// 状态文本：含历史兼容状态（历史工单仍需正常显示，不崩溃）
export const WO_STATUS_TEXT = {
  pending_dispatch: '待派发（历史）',
  pending_accept: '待接单（历史）',
  executing: '执行中',
  pending_review: '待复核（历史）',
  completed: '已完成',
  closed: '已关闭',
  cancelled: '已取消',
};

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
  inspection_record: '来源巡检异常',
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

// 台账类型 → 路由路径（来源/目标跳转用；旧巡检类型已删除，
// legacy 快照来源在详情页仅展示文本，不做跳转）
export const LEDGER_TYPE_PATH = {
  week_month: '/el/week-month-ledgers',
  seasonal: '/el/seasonal-ledgers',
};

export const API_PREFIX = '/api/equipment-lifecycle';
