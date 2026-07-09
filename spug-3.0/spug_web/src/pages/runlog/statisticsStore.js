/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import moment from 'moment';

class Store {
  @observable isFetching = false;
  @observable data = null;

  // 筛选条件（默认最近 30 天）
  @observable f_date_range = [
    moment().subtract(29, 'days'),
    moment(),
  ];
  @observable f_event_type;
  @observable f_system_name;
  @observable f_severity;
  @observable f_status;

  // 事件类型 / 系统名称 下拉选项
  @observable eventTypes = [];
  @observable systemNames = [];

  @action fetchOverview = () => {
    this.isFetching = true;
    const params = { _t: Date.now() };
    if (this.f_date_range && this.f_date_range.length === 2) {
      params.start_date = this.f_date_range[0].format('YYYY-MM-DD');
      params.end_date = this.f_date_range[1].format('YYYY-MM-DD');
    }
    if (this.f_event_type) params.event_type = this.f_event_type;
    if (this.f_system_name) params.system_name = this.f_system_name;
    if (this.f_severity) params.severity = this.f_severity;
    if (this.f_status) params.status = this.f_status;

    return http.get('/api/runlog/overview/', { params })
      .then(res => {
        this.data = res;
        return res;
      })
      .catch(e => {
        console.error('[跨日事项跟踪统计概览] 获取数据失败:', e);
        throw e;
      })
      .finally(() => { this.isFetching = false; });
  };

  // 获取事件类型下拉（复用已有接口）
  @action fetchEventTypes = () => {
    return http.get('/api/runlog/event_types/')
      .then(res => { this.eventTypes = res || []; })
      .catch(e => { console.error('[跨日事项跟踪统计概览] 获取事件类型失败:', e); });
  };

  // 获取系统名称下拉（复用列表接口返回的 system_names）
  @action fetchSystemNames = () => {
    return http.get('/api/runlog/', { params: { page: 1, page_size: 1, _t: Date.now() } })
      .then(res => { this.systemNames = res.system_names || []; })
      .catch(e => { console.error('[跨日事项跟踪统计概览] 获取系统名称失败:', e); });
  };

  @action setFilter = (key, value) => {
    this[`f_${key}`] = value;
  };

  @action resetFilters = () => {
    this.f_date_range = [moment().subtract(29, 'days'), moment()];
    this.f_event_type = undefined;
    this.f_system_name = undefined;
    this.f_severity = undefined;
    this.f_status = undefined;
  };
}

export default new Store();
