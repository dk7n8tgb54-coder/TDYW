/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */

// 设备状态映射（语义对齐 apps.device DeviceResume.STATUS_CHOICES，仅用于只读展示）
export const DEVICE_STATUS_MAP = {
  '1': {text: '正常', color: 'green'},
  '2': {text: '故障', color: 'red'},
  '3': {text: '维修中', color: 'orange'},
  '4': {text: '停用', color: 'gray'},
  '5': {text: '报废', color: 'gray'},
};

export const DEVICE_STATUS_OPTIONS = Object.entries(DEVICE_STATUS_MAP).map(([value, item]) => ({
  value,
  label: item.text,
}));

export const getDeviceStatusConfig = (status) => {
  return DEVICE_STATUS_MAP[status] || {text: status || '未知', color: 'default'};
};

// 位置变更类型（initial 仅由建档流程服务端写入，前端只提供以下两种）
export const LOCATION_CHANGE_TYPE_OPTIONS = [
  {value: 'relocation', label: '位置搬迁'},
  {value: 'correction', label: '位置更正'},
];
