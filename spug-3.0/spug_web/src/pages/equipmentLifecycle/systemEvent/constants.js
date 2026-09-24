/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——统一系统履历（步骤 3.4，单系统简化）常量与来源跳转。
 * 权限码与后端 @auth、role codes.js 保持一致。
 * 履历只读（append-only）：无新增/编辑/删除入口；
 * 一条事件只关联一个系统，不再有跨系统角色（primary/affected/related 已删）。
 */
import { hasPermission } from 'libs';
import { LEDGER_TYPE_PATH } from '../workOrder/constants';

export const PERM = {
  EVENT_VIEW: 'equipment_lifecycle.system_event.view',
  EVENT_EXPORT: 'equipment_lifecycle.system_event.export',
};

export const API_PREFIX = '/api/equipment-lifecycle';

export const EVENT_TYPE_OPTIONS = [
  {value: 'fault', label: '故障'},
  {value: 'work_order', label: '工单'},
  {value: 'ledger', label: '台账异常'},
  {value: 'inspection', label: '值班巡检'},
  {value: 'health', label: '健康状态'},
  {value: 'config_snapshot', label: '配置快照'},
  {value: 'upgrade', label: '系统升级'},
];

export const EVENT_TYPE_TEXT = EVENT_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label;
  return acc;
}, {});

export const EVENT_TYPE_COLOR = {
  fault: 'red',
  work_order: 'geekblue',
  ledger: 'orange',
  inspection: 'cyan',
  health: 'purple',
  config_snapshot: 'cyan',
  upgrade: 'gold',
};

export const SOURCE_TYPE_TEXT = {
  fault: '故障',
  work_order: '工单',
  ledger_item: '台账异常',
  inspection_record: '巡检异常',
  health: '健康状态',
  config_snapshot: '配置快照',
  upgrade: '系统升级',
};

/**
 * 来源跳转地址：履历只携带 source_type/source_id（与摘要），
 * 跳转后由来源页面独立重新校验对象权限与租户。
 * 无对应权限或无来源对象（如健康状态事件）时返回 null，不渲染链接。
 */
export function buildSourceHref(event) {
  if (!event) return null;
  const id = event.source_id;
  switch (event.source_type) {
    case 'fault':
      return hasPermission('equipment_lifecycle.fault.view') && id
        ? `/el/faults?detail=${id}` : null;
    case 'work_order':
      return hasPermission('equipment_lifecycle.work_order.view') && id
        ? `/el/work-orders?detail=${id}` : null;
    case 'ledger_item': {
      const detail = event.detail || {};
      const path = LEDGER_TYPE_PATH[detail.ledger_type];
      return hasPermission('equipment_lifecycle.ledger.view') && path && detail.ledger_id
        ? `${path}?detail=${detail.ledger_id}` : null;
    }
    case 'inspection_record': {
      // 值班巡检异常转单事件：跳到巡检单记录页打开来源巡检单
      const detail = event.detail || {};
      return hasPermission('equipment_lifecycle.inspection.view') && detail.sheet_id
        ? `/el/inspection-sheets?detail=${detail.sheet_id}` : null;
    }
    case 'upgrade':
      // 升级记录工作台为全屏页，按升级表单查看权限跳转
      return hasPermission('upgrade.upgrade.view') && id
        ? `/upgrade/workbench/${id}` : null;
    default:
      return null;
  }
}
