/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */

// 设备状态映射（统一管理）
export const DEVICE_STATUS_MAP = {
  '1': { text: '正常', color: 'green', icon: '🟢', aria: '正常状态', hex: '#52c41a' },
  '2': { text: '故障', color: 'red', icon: '🔴', aria: '故障状态', hex: '#ff4d4f' },
  '3': { text: '维修中', color: 'orange', icon: '🟠', aria: '维修中状态', hex: '#faad14' },
  '4': { text: '停用', color: 'gray', icon: '⚫', aria: '停用状态', hex: '#999999' },
  '5': { text: '报废', color: 'gray', icon: '⚫', aria: '报废状态', hex: '#999999' }
};

// 事件类型映射（统一管理）
export const EVENT_TYPE_MAP = {
  '1': { text: '重大故障维修', color: 'red', hex: '#ff4d4f' },
  '2': { text: '设备更新', color: 'orange', hex: '#faad14' },
  '3': { text: '设备检修', color: 'blue', hex: '#1890ff' }
};

// 获取设备状态配置的工具函数
export const getDeviceStatusConfig = (status) => {
  return DEVICE_STATUS_MAP[status] || { text: status || '未知', color: 'default', icon: '🟡', aria: '未知状态', hex: '#999999' };
};

// 获取事件类型配置的工具函数
export const getEventTypeConfig = (type) => {
  return EVENT_TYPE_MAP[type] || { text: '未知', color: 'default', hex: '#999999' };
};
