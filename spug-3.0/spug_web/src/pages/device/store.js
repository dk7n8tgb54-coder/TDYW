/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

/**
 * 设备履历管理系统状态管理 Store
 * 职责：设备档案管理、设备详情查看、事件增删改查
 */
class Store {
  // ========== 设备档案管理状态 ==========
  @observable records = [];           // 设备档案列表
  @observable useUnits = [];           // 使用单位选项
  @observable deviceModels = [];        // 设备型号选项
  @observable isFetching = false;      // 设备列表加载状态
  @observable total = 0;               // 设备总数
  @observable page = 1;                 // 设备列表当前页码
  @observable pageSize = 20;           // 设备列表每页数量

  // ========== 设备表单状态 ==========
  @observable formVisible = false;      // 设备履历表单可见性
  @observable record = {};             // 当前编辑/新增的设备档案（默认空对象避免空值报错）

  // ========== 设备详情弹窗状态 ==========
  @observable detailVisible = false;   // 设备详情弹窗可见性

  // ========== 事件管理状态 ==========
  @observable eventRecords = [];        // 事件记录列表
  @observable eventTotal = 0;          // 事件总数
  @observable eventPage = 1;            // 事件列表当前页码
  @observable eventPageSize = 20;      // 事件列表每页数量
  @observable eventTypeFilter = null;  // 事件类型筛选（null=全部）

  // ========== 事件表单状态 ==========
  @observable eventFormVisible = false;      // 事件表单可见性
  @observable eventFormRecord = {};          // 事件表单数据（默认空对象）
  @observable eventFormDeviceResume = null;  // 事件表单关联的设备履历
  @observable isSubmittingEvent = false;     // 事件表单提交中状态（防止重复提交）

  // ========== 筛选条件状态 ==========
  @observable f_device_sn = null;      // 筛选：设备编号
  @observable f_device_name = null;    // 筛选：设备名称
  @observable f_device_model = null;   // 筛选：设备型号
  @observable f_current_status = [];   // 筛选：当前状态（数组）
  @observable f_use_unit = null;       // 筛选：使用单位

  // ========== 设备档案 CRUD ==========
  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.page,
      page_size: this.pageSize
    };
    if (this.f_device_sn) params.device_sn = this.f_device_sn;
    if (this.f_device_name) params.device_name = this.f_device_name;
    if (this.f_device_model) params.device_model = this.f_device_model;
    if (this.f_current_status && this.f_current_status.length > 0) params.current_status = this.f_current_status;
    if (this.f_use_unit) params.use_unit = this.f_use_unit;

    http.get('/api/device/device-resume/', { params })
      .then(res => {
        this.records = res.data;
        this.total = res.total;
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '获取设备列表失败');
      })
      .finally(() => {
        this.isFetching = false
      })
  };

  fetchFilterOptions = () => {
    const promises = [];
    promises.push(http.get('/api/device/device-resume/?use_units=1').then(res => {
      this.useUnits = res;
    }));
    promises.push(http.get('/api/device/device-resume/?device_models=1').then(res => {
      this.deviceModels = res;
    }));
    return Promise.all(promises);
  };

  fetchRecord = (id) => {
    return http.get(`/api/device/device-resume/?id=${id}`)
  };

  // ========== 事件管理 CRUD ==========
  fetchEvents = (deviceResumeId) => {
    const params = {
      device_resume_id: deviceResumeId,
      page: this.eventPage,
      page_size: this.eventPageSize
    };
    if (this.eventTypeFilter) params.event_type = this.eventTypeFilter;

    return http.get('/api/device/device-event/', { params })
      .then(res => {
        this.eventRecords = res.data;
        this.eventTotal = res.total;
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '获取事件列表失败');
        throw err;
      })
  };

  setEventTypeFilter = (filterType, deviceResumeId) => {
    this.eventTypeFilter = filterType === 'all' || filterType === '' ? null : filterType;
    this.eventPage = 1;
    if (deviceResumeId) {
      this.fetchEvents(deviceResumeId);
    }
  };

  // ========== 设备表单操作 ==========
  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = {...info};
  };

  showDetail = (record) => {
    this.record = record;
    this.detailVisible = true;
    this.eventPage = 1;
    this.eventTypeFilter = null;
    this.fetchEvents(record.id);
  };

  handleAdd = (values) => {
    return http.post('/api/device/device-resume/', values)
      .then(() => {
        this.formVisible = false;
        this.fetchRecords();
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '添加设备履历失败');
        throw err;
      })
  };

  handleUpdate = (values) => {
    return http.put('/api/device/device-resume/', values)
      .then(() => {
        this.formVisible = false;
        this.fetchRecords();
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '更新设备履历失败');
        throw err;
      })
  };

  handleDelete = (id) => {
    return http.delete('/api/device/device-resume/', { params: { id } })
      .then(() => {
        this.fetchRecords();
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '删除设备履历失败');
        throw err;
      })
  };

  // ========== 事件 CRUD ==========
  handleAddEvent = (values) => {
    if (this.isSubmittingEvent) {
      return Promise.reject(new Error('正在提交中，请勿重复操作'));
    }
    this.isSubmittingEvent = true;
    return http.post('/api/device/device-event/', values)
      .then(() => {
        this.fetchEvents(values.device_resume_id);
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '添加事件失败');
        throw err;
      })
      .finally(() => {
        this.isSubmittingEvent = false;
      })
  };

  handleUpdateEvent = (values) => {
    if (this.isSubmittingEvent) {
      return Promise.reject(new Error('正在提交中，请勿重复操作'));
    }
    this.isSubmittingEvent = true;
    return http.put('/api/device/device-event/', values)
      .then(() => {
        this.fetchEvents(this.record.id);
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '更新事件失败');
        throw err;
      })
      .finally(() => {
        this.isSubmittingEvent = false;
      })
  };

  handleDeleteEvent = (id) => {
    return http.delete('/api/device/device-event/', { params: { id } })
      .then(() => {
        this.fetchEvents(this.record.id);
      })
      .catch(err => {
        const { message } = require('antd');
        message.error(err.message || '删除事件失败');
        throw err;
      })
  };

  // ========== 筛选操作 ==========
  resetFilter = () => {
    this.f_device_sn = null;
    this.f_device_name = null;
    this.f_device_model = null;
    this.f_current_status = [];
    this.f_use_unit = null;
    this.page = 1;
    this.fetchRecords();
  };
}

export default new Store()
