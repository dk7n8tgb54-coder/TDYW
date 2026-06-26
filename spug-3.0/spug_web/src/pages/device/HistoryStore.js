/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http, exportFile } from 'libs';

/**
 * 设备履历查看页面 Store
 * 职责：管理设备选择、设备信息获取、事件展示的独立业务逻辑
 * 注意：此 Store 与 store.js 的设备档案管理职责不同，独立维护
 */
class Store {
  // ========== 设备选择状态 ==========
  @observable devices = [];           // 设备列表
  @observable selectedDeviceId = null; // 当前选中的设备ID
  @observable isFetchingDevices = false; // 设备列表加载状态

  // ========== 设备信息状态 ==========
  @observable deviceInfo = null;       // 当前选中设备的信息
  @observable isFetchingInfo = false;  // 设备信息加载状态

  // ========== 事件展示状态 ==========
  @observable events = [];              // 事件列表
  @observable eventTypeFilter = 'all';  // 事件类型筛选（all=全部，1/2/3=具体类型）
  @observable isFetchingEvents = false; // 事件列表加载状态

  // ========== 导出状态 ==========
  @observable isExporting = false;      // PDF导出中

  // ========== 设备选择与信息获取 ==========
  fetchDevices = () => {
    this.isFetchingDevices = true;
    // 获取所有设备（不分页），用于下拉框选择
    http.get('/api/device/device-resume/', { params: { page_size: 9999 } })
      .then(data => {
        this.devices = data.data || [];
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '获取设备列表失败');
      })
      .finally(() => this.isFetchingDevices = false);
  };

  selectDevice = (deviceId) => {
    this.selectedDeviceId = deviceId;
    if (deviceId) {
      this.fetchDeviceInfo(deviceId);
      this.fetchEvents(deviceId);
    } else {
      this.deviceInfo = null;
      this.events = [];
    }
  };

  fetchDeviceInfo = (deviceId) => {
    this.isFetchingInfo = true;
    http.get('/api/device/device-resume/', { params: { id: deviceId } })
      .then(data => {
        this.deviceInfo = data;
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '获取设备信息失败');
      })
      .finally(() => this.isFetchingInfo = false);
  };

  // ========== 事件获取与筛选 ==========
  fetchEvents = (deviceId, eventType = null) => {
    this.isFetchingEvents = true;
    const params = { device_resume_id: deviceId };
    if (eventType && eventType !== 'all') {
      params.event_type = eventType;
    }
    http.get('/api/device/device-event/', { params })
      .then(data => {
        this.events = data.data || [];
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '获取事件列表失败');
      })
      .finally(() => this.isFetchingEvents = false);
  };

  setEventTypeFilter = (filterType) => {
    this.eventTypeFilter = filterType;
    if (this.selectedDeviceId) {
      this.fetchEvents(this.selectedDeviceId, filterType === 'all' ? null : filterType);
    }
  };

  // ========== PDF导出 ==========
  exportPDF = async () => {
    if (!this.deviceInfo) {
      const { message } = require('antd');
      message.warning('请先选择设备');
      return;
    }

    this.isExporting = true;
    const deviceSn = this.deviceInfo.device_sn || 'unknown';
    const deviceName = this.deviceInfo.device_name || '';
    const exportTime = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const ts = `${exportTime.getFullYear()}${pad(exportTime.getMonth() + 1)}${pad(exportTime.getDate())}_${pad(exportTime.getHours())}${pad(exportTime.getMinutes())}${pad(exportTime.getSeconds())}`;
    try {
      await exportFile({
        url: '/api/device/device-resume/export/pdf/',
        method: 'post',
        data: { device_info: this.deviceInfo, events: this.events },
        defaultFilename: `设备履历_${deviceSn}_${deviceName}_${ts}.pdf`,
        timeout: 60000,
        loadingText: '正在生成PDF...',
      });
    } finally {
      this.isExporting = false;
    }
  };
}

export default new Store()
