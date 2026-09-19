/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——当前运行状态状态管理（MobX, legacy decorators）。
 * 汇总（status-summary）与状态列表（/systems/ 复用，只读）分开展示。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from '../constants';

class SummaryStore {
  @observable summary = {};
  @observable total = 0;
  @observable activeTotal = 0;
  @observable inactiveTotal = 0;
  @observable isSummaryFetching = false;

  fetchSummary = () => {
    this.isSummaryFetching = true;
    return http.get(`${API_PREFIX}/systems/status-summary/`)
      .then(action(res => {
        this.summary = res.summary || {};
        this.total = res.total;
        this.activeTotal = res.active_total;
        this.inactiveTotal = res.inactive_total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isSummaryFetching = false;
      }));
  };
}

class StatusListStore {
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;
  @observable f_keyword = undefined;
  @observable f_health_status = undefined;

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_health_status) params.health_status = this.f_health_status;
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

  filterByStatus = action((status) => {
    this.f_health_status = status;
    this.page = 1;
    this.fetchRecords();
  });
}

export const summaryStore = new SummaryStore();
export const listStore = new StatusListStore();
