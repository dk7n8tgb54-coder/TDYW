/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障管理状态管理（MobX, legacy decorators）。
 * 业务关联一律使用系统 ID；成功提示等待后端真实成功（http.js 拦截器统一提示 error）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from './constants';

class FaultStore {
  // ========== 故障列表 ==========
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // ========== 筛选条件 ==========
  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_level = undefined;
  @observable f_system = undefined;
  @observable f_occurred_range = undefined;

  // ========== 表单 ==========
  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;

  // ========== 系统候选项 ==========
  @observable systems = [];

  // ========== 详情抽屉 ==========
  @observable detailVisible = false;
  @observable detailId = null;
  @observable detail = {};
  @observable isDetailFetching = false;

  // ========== 处理进展（原处置记录） ==========
  @observable handlingRecords = [];
  @observable isHandlingFetching = false;

  // ========== 动作执行中 ==========
  @observable isActionSubmitting = false;

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_level = undefined;
    this.f_system = undefined;
    this.f_occurred_range = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_level) params.level = this.f_level;
    if (this.f_system) params.system = this.f_system;
    if (this.f_occurred_range && this.f_occurred_range.length === 2) {
      params.occurred_from = this.f_occurred_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.f_occurred_range[1].format('YYYY-MM-DD HH:mm');
    }
    return http.get(`${API_PREFIX}/faults/`, {params})
      .then(action(res => {
        this.records = res.data;
        this.total = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  fetchSystems = () => {
    return http.get(`${API_PREFIX}/faults/candidate-systems/`)
      .then(action(res => {
        this.systems = res.data;
      }))
      .catch(action(() => {}));
  };

  systemOption = (id) => {
    return this.systems.find(s => s.id === id);
  };

  showForm = action((record = {}) => {
    this.record = record;
    this.formVisible = true;
    this.fetchSystems();
  });

  submitForm = (formData) => {
    this.isSubmitting = true;
    const isEdit = !!this.record.id;
    const request = isEdit
      ? http.put(`${API_PREFIX}/faults/${this.record.id}/`, formData)
      : http.post(`${API_PREFIX}/faults/`, formData);
    return request
      .then(action(() => {
        this.formVisible = false;
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  showDetail = action((recordOrId) => {
    // 支持对象或纯 ID（跨页 ?detail= 跳转直达详情）
    this.detailId = typeof recordOrId === 'object' ? recordOrId.id : recordOrId;
    this.detail = typeof recordOrId === 'object' ? recordOrId : {};
    this.detailVisible = true;
    this.handlingRecords = [];
    this.fetchDetail();
    this.fetchHandlingRecords();
  });

  closeDetail = action(() => {
    this.detailVisible = false;
    this.detailId = null;
  });

  fetchDetail = () => {
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX}/faults/${this.detailId}/`)
      .then(action(res => {
        // http 拦截器已解包 json_response 的 data 层，res 即详情本体
        this.detail = res;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isDetailFetching = false;
      }));
  };

  fetchDetailById = (id) => {
    // 与 fetchDetail 一致：resolve 详情本体，供编辑表单回填
    return http.get(`${API_PREFIX}/faults/${id}/`);
  };

  fetchHandlingRecords = () => {
    this.isHandlingFetching = true;
    return http.get(`${API_PREFIX}/faults/${this.detailId}/handling-records/`)
      .then(action(res => {
        this.handlingRecords = res.data;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isHandlingFetching = false;
      }));
  };

  // ========== 状态动作（成功后重新获取真实数据） ==========
  startHandling = (extra = {}) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/start/`, extra)
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  confirmRecover = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/recover/`, formData)
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  closeFault = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/close/`, formData)
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  cancelFault = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/cancel/`, formData)
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  addHandlingRecord = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/handling-records/`, formData)
      .then(action(() => {
        this.fetchHandlingRecords();
        this.fetchDetail();
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  correctHandlingRecord = (recordId, formData) => {
    this.isActionSubmitting = true;
    return http.put(
      `${API_PREFIX}/faults/${this.detailId}/handling-records/${recordId}/`, formData)
      .then(action(() => {
        this.fetchHandlingRecords();
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  _refreshAfterAction = () => {
    this.fetchDetail();
    this.fetchHandlingRecords();
    this.fetchRecords();
  };

  // ========== 系统详情故障页签（单系统简化：只查本系统故障） ==========
  @observable systemFaults = [];
  @observable isSystemFaultsFetching = false;

  fetchSystemFaults = (systemId) => {
    this.isSystemFaultsFetching = true;
    return http.get(`${API_PREFIX}/systems/${systemId}/faults/`)
      .then(action(res => {
        this.systemFaults = res.data || [];
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isSystemFaultsFetching = false;
      }));
  };
}

export default new FaultStore();
