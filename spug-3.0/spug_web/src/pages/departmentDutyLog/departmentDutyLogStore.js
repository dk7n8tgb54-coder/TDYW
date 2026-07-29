/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import {observable, action} from 'mobx';
import {http} from 'libs';

class DepartmentDutyLogStore {
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable pageNum = 1;
  @observable pageSize = 20;

  @observable formVisible = false;
  @observable detailVisible = false;
  @observable detailLoading = false;
  @observable signVisible = false;
  @observable returnVisible = false;
  @observable record = {};
  @observable formRecord = {};

  // 筛选
  @observable f_start_date = undefined;
  @observable f_end_date = undefined;
  @observable f_duty_person_name = undefined;
  @observable f_status = undefined;
  @observable f_keyword = undefined;

  // 选项
  @observable currentUser = null;

  // 日期选择器面板上"已有值班日志"的日期集合，按 "YYYY-MM" 缓存
  // 结构：{ 'YYYY-MM': Set(['YYYY-MM-DD', ...]) }
  @observable dutyDatesByMonth = {};
  @observable dutyDatesLoading = false;

  // 常量
  statusOptions = [
    {value: 'draft', label: '草稿'},
    {value: 'signed', label: '已签署'},
  ];

  statusTagMap = {
    draft: {color: 'default', text: '草稿'},
    signed: {color: 'green', text: '已签署'},
  };

  @action.bound
  fetchRecords() {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize,
    };
    if (this.f_start_date) params.start_date = this.f_start_date.format('YYYY-MM-DD');
    if (this.f_end_date) params.end_date = this.f_end_date.format('YYYY-MM-DD');
    if (this.f_duty_person_name) params.duty_person_name = this.f_duty_person_name;
    if (this.f_status) params.status = this.f_status;
    if (this.f_keyword) params.keyword = this.f_keyword;

    http.get('/api/department-duty-log/records/', {params})
      .then(({records, total, page, page_size}) => {
        this.records = records || [];
        this.total = total || 0;
      })
      .finally(() => this.isFetching = false);
  }

  @action.bound
  fetchOptions() {
    http.get('/api/department-duty-log/options/')
      .then(data => {
        this.currentUser = data.current_user;
      });
  }

  @action.bound
  showForm(record) {
    this.formRecord = record || {};
    this.formVisible = true;
  }

  @action.bound
  showDetail(record) {
    // 先用列表 record 占位立即可见，再异步拉详情接口补全长文本字段
    // （列表仅返回 duty_record_summary，详情接口才返回 duty_record / remark 全文）
    this.record = record;
    this.detailVisible = true;
    this.detailLoading = true;
    http.get(`/api/department-duty-log/records/${record.id}/`)
      .then(data => {
        this.record = data;
      })
      .catch(() => {
        // 详情接口失败：http 拦截器已提示错误，关闭抽屉避免占位 record 误导用户
        this.detailVisible = false;
      })
      .finally(() => this.detailLoading = false);
  }

  @action.bound
  showSign(record) {
    this.record = record;
    this.signVisible = true;
  }

  @action.bound
  showReturn(record) {
    this.record = record;
    this.returnVisible = true;
  }

  /**
   * 拉取指定月份的已有值班日志日期，结果缓存到 dutyDatesByMonth。
   * 已缓存的月份不会重复请求。year/month 为整数。
   */
  @action.bound
  fetchDutyDatesByMonth(year, month) {
    const key = `${year}-${String(month).padStart(2, '0')}`;
    if (this.dutyDatesByMonth[key]) return Promise.resolve(this.dutyDatesByMonth[key]);

    this.dutyDatesLoading = true;
    return http
      .get('/api/department-duty-log/records/duty_dates/', {params: {year, month}})
      .then(data => {
        const set = new Set(data.dates || []);
        this.dutyDatesByMonth = {...this.dutyDatesByMonth, [key]: set};
        return set;
      })
      .finally(() => this.dutyDatesLoading = false);
  }

  /**
   * 判断某日期是否已有值班日志。无缓存时返回 false（同步），
   * 调用方应先 fetchDutyDatesByMonth 把当前面板月份数据拉到。
   */
  hasDutyDate(dateStr) {
    const [y, m] = dateStr.split('-');
    const key = `${y}-${m}`;
    const set = this.dutyDatesByMonth[key];
    return !!(set && set.has(dateStr));
  }
}

export default new DepartmentDutyLogStore();
