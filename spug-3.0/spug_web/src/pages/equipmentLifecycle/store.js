/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统列表/详情状态管理（MobX, legacy decorators）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from './constants';

class Store {
  // ========== 系统列表 ==========
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // ========== 筛选条件 ==========
  @observable f_keyword = undefined;
  @observable f_health_status = undefined;
  @observable f_is_active = undefined;
  @observable f_use_unit = undefined;
  @observable f_install_location = undefined;

  // ========== 新增/编辑表单 ==========
  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;

  // ========== 详情抽屉 ==========
  @observable detailVisible = false;
  @observable detail = {};
  @observable isDetailFetching = false;

  // ========== 详情动态字段（基本信息展示 + 表单加载） ==========
  @observable formFields = [];
  @observable isFormFieldsFetching = false;

  // ========== 配置组成项 ==========
  @observable components = [];
  @observable isComponentsFetching = false;
  @observable componentFormVisible = false;
  @observable componentRecord = {};

  // ========== 变更历史 ==========
  @observable changes = [];
  @observable changesTotal = 0;
  @observable changesPage = 1;
  @observable isChangesFetching = false;

  // ========== 配置快照 ==========
  @observable snapshots = [];
  @observable snapshotsTotal = 0;
  @observable isSnapshotsFetching = false;
  @observable snapshotFormVisible = false;
  @observable snapshotDiff = null;

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_health_status = undefined;
    this.f_is_active = undefined;
    this.f_use_unit = undefined;
    this.f_install_location = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_health_status) params.health_status = this.f_health_status;
    if (this.f_is_active !== undefined && this.f_is_active !== null) params.is_active = this.f_is_active;
    if (this.f_use_unit) params.use_unit = this.f_use_unit;
    if (this.f_install_location) params.install_location = this.f_install_location;
    return http.get(`${API_PREFIX}/systems/`, {params})
      .then(action(res => {
        this.records = res.data;
        this.total = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  showForm = action((record = {}) => {
    this.record = record;
    this.formVisible = true;
  });

  submitForm = (formData) => {
    this.isSubmitting = true;
    const isEdit = !!this.record.id;
    const request = isEdit
      ? http.put(`${API_PREFIX}/systems/${this.record.id}/`, formData)
      : http.post(`${API_PREFIX}/systems/`, formData);
    return request
      .then(action(() => {
        this.formVisible = false;
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  toggleActive = (record, is_active) => {
    return http.post(`${API_PREFIX}/systems/${record.id}/active/`, {is_active})
      .then(action(() => {
        this.fetchRecords();
      }));
  };

  deleteRecord = (record) => {
    return http.delete(`${API_PREFIX}/systems/${record.id}/`)
      .then(action(() => {
        this.fetchRecords();
      }));
  };

  showDetail = action((record) => {
    this.detailId = record.id;
    this.detail = record;
    this.detailVisible = true;
    this.components = [];
    this.changes = [];
    this.snapshots = [];
    this.snapshotDiff = null;
    this.fetchDetail();
  });

  closeDetail = action(() => {
    this.detailVisible = false;
    this.detailId = null;
  });

  fetchDetail = () => {
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX}/systems/${this.detailId}/`)
      .then(action(res => {
        this.detail = res;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isDetailFetching = false;
      }));
  };

  // ========== 表单动态字段（新增/编辑系统一次提交） ==========
  fetchFormFields = (params) => {
    this.isFormFieldsFetching = true;
    return http.get(`${API_PREFIX}/systems/form-fields/`, {params})
      .then(action(res => {
        this.formFields = res.data || [];
        return res;
      }))
      .finally(action(() => {
        this.isFormFieldsFetching = false;
      }));
  };

  // ========== 系统附件（动态字段 attachment 类型） ==========
  fetchSystemAttachments = (systemId) => {
    return http.get(`${API_PREFIX}/systems/${systemId}/config/attachments/`);
  };

  uploadSystemAttachment = (systemId, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return http.post(
      `${API_PREFIX}/systems/${systemId}/config/attachments/`, formData,
      {headers: {'Content-Type': 'multipart/form-data'}});
  };

  deleteSystemAttachment = (systemId, attId) => {
    return http.delete(`${API_PREFIX}/systems/${systemId}/config/attachments/${attId}/`);
  };

  // ========== 配置组成项 ==========
  fetchComponents = () => {
    this.isComponentsFetching = true;
    return http.get(`${API_PREFIX}/systems/${this.detailId}/components/`)
      .then(action(res => {
        this.components = res.data;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isComponentsFetching = false;
      }));
  };

  showComponentForm = action((record = {}) => {
    this.componentRecord = record;
    this.componentFormVisible = true;
  });

  submitComponent = (formData) => {
    this.isSubmitting = true;
    const isEdit = !!this.componentRecord.id;
    const request = isEdit
      ? http.put(`${API_PREFIX}/systems/${this.detailId}/components/${this.componentRecord.id}/`, formData)
      : http.post(`${API_PREFIX}/systems/${this.detailId}/components/`, formData);
    return request
      .then(action(() => {
        this.componentFormVisible = false;
        this.fetchComponents();
        this.fetchDetail();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  deleteComponent = (record) => {
    return http.delete(`${API_PREFIX}/systems/${this.detailId}/components/${record.id}/`)
      .then(action(() => {
        this.fetchComponents();
        this.fetchDetail();
      }));
  };

  // ========== 自定义字段 ==========
  createCustomField = (formData) => {
    return http.post(`${API_PREFIX}/systems/${this.detailId}/custom-fields/`, formData);
  };

  updateCustomField = (fieldId, formData) => {
    return http.put(`${API_PREFIX}/systems/${this.detailId}/custom-fields/${fieldId}/`, formData);
  };

  deleteCustomField = (fieldId) => {
    return http.delete(`${API_PREFIX}/systems/${this.detailId}/custom-fields/${fieldId}/`);
  };

  toggleCustomField = (record) => {
    return this.updateCustomField(record.id, {...record, is_active: !record.is_active});
  };

  // ========== 变更历史 ==========
  fetchChanges = () => {
    this.isChangesFetching = true;
    return http.get(`${API_PREFIX}/systems/${this.detailId}/changes/`,
      {params: {page: this.changesPage, page_size: 10}})
      .then(action(res => {
        this.changes = res.data;
        this.changesTotal = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isChangesFetching = false;
      }));
  };

  // ========== 配置快照 ==========
  fetchSnapshots = () => {
    this.isSnapshotsFetching = true;
    return http.get(`${API_PREFIX}/systems/${this.detailId}/snapshots/`)
      .then(action(res => {
        this.snapshots = res.data;
        this.snapshotsTotal = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isSnapshotsFetching = false;
      }));
  };

  createSnapshot = (formData) => {
    return http.post(`${API_PREFIX}/systems/${this.detailId}/snapshots/`, formData)
      .then(action(() => {
        this.snapshotFormVisible = false;
        this.fetchSnapshots();
      }));
  };

  fetchSnapshotDiff = (snapshotId, target = 'current') => {
    return http.get(`${API_PREFIX}/systems/${this.detailId}/snapshots/${snapshotId}/`,
      {params: {target}})
      .then(action(res => {
        this.snapshotDiff = res;
      }));
  };

  clearSnapshotDiff = action(() => {
    this.snapshotDiff = null;
  });
}

export default new Store();
