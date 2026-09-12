/**
 * 设备台账/履历 常量映射测试
 *
 * DEVICE_STATUS_MAP / EVENT_TYPE_MAP 是设备与事件展示的统一来源，
 * 防止状态码新增后映射缺失导致页面显示空白。
 */
import {
  DEVICE_STATUS_MAP,
  EVENT_TYPE_MAP,
  getDeviceStatusConfig,
  getEventTypeConfig,
} from '../constants';

describe('设备状态映射', () => {
  it('五个状态码均有展示配置', () => {
    Object.keys(DEVICE_STATUS_MAP).forEach(code => {
      const conf = DEVICE_STATUS_MAP[code];
      expect(conf.text).toBeTruthy();
      expect(conf.color).toBeTruthy();
      expect(conf.hex).toMatch(/^#/);
    });
    expect(DEVICE_STATUS_MAP['1'].text).toBe('正常');
    expect(DEVICE_STATUS_MAP['2'].text).toBe('故障');
    expect(DEVICE_STATUS_MAP['3'].text).toBe('维修中');
    expect(DEVICE_STATUS_MAP['4'].text).toBe('停用');
    expect(DEVICE_STATUS_MAP['5'].text).toBe('报废');
  });

  it('getDeviceStatusConfig 已知状态返回映射配置', () => {
    expect(getDeviceStatusConfig('1').text).toBe('正常');
    expect(getDeviceStatusConfig('3').text).toBe('维修中');
  });

  it('getDeviceStatusConfig 未知状态回显原始码、空状态兜底为未知', () => {
    // 未映射的状态码原样回显（便于发现新状态码未配映射的问题）
    expect(getDeviceStatusConfig('99').text).toBe('99');
    expect(getDeviceStatusConfig('99').color).toBe('default');
    expect(getDeviceStatusConfig('').text).toBe('未知');
    expect(getDeviceStatusConfig(undefined).text).toBe('未知');
  });
});

describe('事件类型映射', () => {
  it('三类事件均有展示配置', () => {
    expect(EVENT_TYPE_MAP['1'].text).toBe('重大故障维修');
    expect(EVENT_TYPE_MAP['2'].text).toBe('设备更新');
    expect(EVENT_TYPE_MAP['3'].text).toBe('设备检修');
  });

  it('getEventTypeConfig 未知类型兜底', () => {
    expect(getEventTypeConfig('99').text).toBe('未知');
    expect(getEventTypeConfig('99').color).toBe('default');
  });
});
