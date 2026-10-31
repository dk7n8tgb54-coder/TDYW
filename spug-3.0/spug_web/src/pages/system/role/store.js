/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, computed } from 'mobx';
import http from 'libs/http';
import codes from './codes';
import lds from 'lodash';

class Store {
  allPerms = {};
  initPerms = {};
  @observable records = [];
  @observable record = {};
  @observable permissions = lds.cloneDeep(codes);
  @observable isFetching = false;
  @observable formVisible = false;
  @observable pagePermVisible = false;

  @observable f_name;

  @computed get dataSource() {
    let records = this.records;
    if (this.f_name) records = records.filter(x => x.name.toLowerCase().includes(this.f_name.toLowerCase()));
    return records
  }

  constructor() {
    this.initPermissions()
  }

  @computed get idMap() {
    const tmp = {}
    for (let item of this.records) {
      tmp[item.id] = item
    }
    return tmp
  }

  fetchRecords = () => {
    this.isFetching = true;
    return http.get('/api/account/role/')
      .then(res => this.records = res)
      .finally(() => this.isFetching = false)
  };

  initPermissions = () => {
    for (let mod of codes) {
      if (!mod.pages) continue;
      this.initPerms[mod.key] = {};
      for (let page of mod.pages) {
        this.initPerms[mod.key][page.key] = [];
        if (!page.perms) continue;
        const allPermKeys = page.perms.map(x => x.key)
        this.allPerms[`${mod.key}.${page.key}`] = allPermKeys
      }
    }
  };

  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = info
  };

  showPagePerm = (info) => {
    this.record = info;
    this.pagePermVisible = true;
    // 使用 mergeWith 实现深度合并，确保合并所有模块的权限；
    // page_perms 必须先深拷贝再合并（customizer 会按引用返回数组），
    // 否则勾选时 push/splice 会原地污染列表里的 record.page_perms，
    // 点「取消」后重新打开会显示未保存的勾选状态
    const result = lds.cloneDeep(this.initPerms);
    const customizer = (objValue, srcValue, key) => {
      // 如果是数组，直接使用 srcValue（后端返回的权限数组）
      if (Array.isArray(srcValue)) {
        return srcValue;
      }
    };
    this.permissions = lds.mergeWith(
      result, lds.cloneDeep(info.page_perms || {}), customizer);
  };
}

export default new Store()
