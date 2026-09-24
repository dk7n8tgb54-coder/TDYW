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

}

export default new Store();
