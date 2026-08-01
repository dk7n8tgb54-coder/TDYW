import { observable } from 'mobx';
import { message } from 'antd';
import { http } from 'libs';

class AlertStore {
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;
  @observable actionId = null;
  @observable summary = {
    unread_count: 0,
    error_count: 0,
    warning_count: 0,
    info_count: 0,
  };

  @observable f_level = '';
  @observable f_status = '';
  @observable f_source = '';
  @observable f_keyword = '';

  // 趋势图状态
  @observable trendData = [];
  @observable trendLoading = false;
  @observable trendHours = 24;

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.page,
      page_size: this.pageSize,
    };
    if (this.f_level) params.level = this.f_level;
    if (this.f_status) params.status = this.f_status;
    if (this.f_source) params.source = this.f_source;
    if (this.f_keyword) params.keyword = this.f_keyword.trim();

    return http.get('/api/alert/', {params})
      .then(res => {
        this.records = res.items || [];
        this.total = res.total || 0;
        this.summary = {...this.summary, ...(res.summary || {})};
      })
      .finally(() => {
        this.isFetching = false;
      });
  };

  search = () => {
    this.page = 1;
    this.fetchRecords();
  };

  resetFilters = () => {
    this.f_level = '';
    this.f_status = '';
    this.f_source = '';
    this.f_keyword = '';
    this.page = 1;
    this.fetchRecords();
  };

  changePage = (page, pageSize) => {
    this.page = page;
    this.pageSize = pageSize;
    this.fetchRecords();
  };

  markRead = id => {
    this.actionId = id;
    return http.post('/api/alert/mark-read/', {ids: [id]})
      .then(() => {
        message.success('已标记为已读');
        return this.fetchRecords();
      })
      .finally(() => {
        this.actionId = null;
      });
  };

  resolve = id => {
    this.actionId = id;
    return http.post(`/api/alert/${id}/resolve/`)
      .then(() => {
        message.success('告警已处理');
        return this.fetchRecords();
      })
      .finally(() => {
        this.actionId = null;
      });
  };

  fetchTrend = () => {
    this.trendLoading = true;
    return http.get('/api/alert/trend/', {params: {hours: this.trendHours}})
      .then(res => {
        this.trendData = res.series || [];
      })
      .finally(() => {
        this.trendLoading = false;
      });
  };

  setTrendHours = (hours) => {
    this.trendHours = hours;
    this.fetchTrend();
  };
}

export default new AlertStore();
