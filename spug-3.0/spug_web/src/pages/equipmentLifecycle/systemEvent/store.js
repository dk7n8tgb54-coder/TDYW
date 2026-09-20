/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——统一系统履历状态管理（MobX, legacy decorators）。
 * 履历只读：仅列表查询（全局/按系统），无新增、修改、删除请求。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from './constants';

export class EventStore {
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // ========== 筛选条件 ==========
  @observable f_keyword = undefined;
  @observable f_event_type = undefined;
  @observable f_source_type = undefined;
  @observable f_range = undefined;

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_event_type = undefined;
    this.f_source_type = undefined;
    this.f_range = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_event_type) params.event_type = this.f_event_type;
    if (this.f_source_type) params.source_type = this.f_source_type;
    if (this.f_range && this.f_range.length === 2) {
      params.occurred_from = this.f_range[0];
      params.occurred_to = this.f_range[1];
    }
    return http.get(`${API_PREFIX}/system-events/`, {params})
      .then(action(res => {
        this.records = res.data || [];
        this.total = res.total || 0;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  /**
   * 按系统查询履历（系统详情页签）：只查当前系统（单系统简化，无角色过滤）。
   * 独立于全局筛选状态，避免详情页签与列表页互相影响。
   */
  fetchSystemEvents = (systemId) => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    return http.get(`${API_PREFIX}/systems/${systemId}/system-events/`, {params})
      .then(action(res => {
        this.records = res.data || [];
        this.total = res.total || 0;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };
}

export default new EventStore();
