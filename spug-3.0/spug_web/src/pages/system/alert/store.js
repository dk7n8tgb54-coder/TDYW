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

    return http.get('/api/home/alert/', {params})
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
    return http.post('/api/home/alert/mark-read/', {ids: [id]})
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
    return http.post(`/api/home/alert/${id}/resolve/`)
      .then(() => {
        message.success('告警已处理');
        return this.fetchRecords();
      })
      .finally(() => {
        this.actionId = null;
      });
  };
}

export default new AlertStore();
