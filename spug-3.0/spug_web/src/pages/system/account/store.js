/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, computed } from 'mobx';
import http from 'libs/http';

class Store {
  @observable records = [];
  @observable record = {};
  @observable isFetching = true;
  @observable formVisible = false;

  @observable f_name;
  @observable f_status = '';
  @observable f_show_deleted = false;

  // 当前登录用户是否超管（动态读取，避免SPA切换用户后缓存过期）
  get isSupper() {
    return localStorage.getItem('is_supper') === 'true'
  }
  // 当前登录用户的tenant_id
  get currentTenantId() {
    return localStorage.getItem('tenant_id') || ''
  }

  @computed get dataSource() {
    let records = this.records;
    if (this.f_name) records = records.filter(x => x.username.toLowerCase().includes(this.f_name.toLowerCase()));
    if (this.f_status) records = records.filter(x => String(x.is_active) === this.f_status);
    return records
  }

  fetchRecords = () => {
    this.isFetching = true;
    const params = {};
    if (this.f_show_deleted) params.show_deleted = 'true';
    http.get('/api/account/user/', {params})
      .then(res => this.records = res)
      .finally(() => this.isFetching = false)
  };

  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = info
  }
}

export default new Store()
