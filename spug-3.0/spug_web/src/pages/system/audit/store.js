/**
 * 操作审计日志Store
 */
import { observable, computed } from 'mobx';
import { http } from 'libs';

class Store {
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // 筛选条件
  @observable f_username = '';
  @observable f_action = '';
  @observable f_target_type = '';
  @observable f_keyword = '';
  @observable f_time_range = null;

  // 操作类型选项
  @observable actionOptions = [];
  // 对象类型选项
  @observable targetTypeOptions = [];

  @computed get dataSource() {
    return this.records;
  }

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.page,
      page_size: this.pageSize,
    };
    if (this.f_username) params.username = this.f_username;
    if (this.f_action) params.action = this.f_action;
    if (this.f_target_type) params.target_type = this.f_target_type;
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_time_range && this.f_time_range[0]) {
      params.start_time = this.f_time_range[0].format('YYYY-MM-DD HH:mm:ss');
    }
    if (this.f_time_range && this.f_time_range[1]) {
      params.end_time = this.f_time_range[1].format('YYYY-MM-DD HH:mm:ss');
    }

    http.get('/api/logs/audit/', { params })
      .then(res => {
        this.records = res.records || [];
        this.total = res.total || 0;
      })
      .finally(() => this.isFetching = false);
  };

  fetchOptions = () => {
    http.get('/api/logs/audit/actions/').then(res => this.actionOptions = res);
    http.get('/api/logs/audit/target_types/').then(res => this.targetTypeOptions = res);
  };

  changePage = (page, pageSize) => {
    this.page = page;
    this.pageSize = pageSize;
    this.fetchRecords();
  };
}

export default new Store()
