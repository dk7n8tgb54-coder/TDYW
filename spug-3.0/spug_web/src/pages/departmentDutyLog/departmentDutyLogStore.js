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
  @observable formLoading = false;
  @observable detailVisible = false;
  @observable detailLoading = false;
  @observable signVisible = false;
  @observable signLoading = false;
  @observable returnVisible = false;
  @observable record = {};
  @observable formRecord = {};

  // 请求序号：丢弃过期异步响应，防止快速切换时竞态覆盖
  _formRequestId = 0;
  _signRequestId = 0;

  // 筛选 - 默认不限制日期，显示全部记录
  @observable f_start_date = undefined;
  @observable f_end_date = undefined;
  @observable f_duty_person_name = undefined;
  @observable f_status = undefined;
  @observable f_keyword = undefined;

  // 选项
  @observable currentUser = null;

  // 日期选择器面板上"已有已签署值班日志"的日期集合，按 "YYYY-MM" 缓存
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
    if (record && record.id) {
      // 编辑模式：详情加载完成后再填表单，防止竞态覆盖
      this.formRecord = {};
      this.formVisible = true;
      this.formLoading = true;
      const reqId = ++this._formRequestId;
      http.get(`/api/department-duty-log/records/${record.id}/`)
        .then(data => {
          if (reqId !== this._formRequestId) return; // 丢弃过期响应
          this.formRecord = data;
          this.formLoading = false;
        })
        .catch(() => {
          if (reqId !== this._formRequestId) return;
          this.formVisible = false;
          this.formLoading = false;
        });
    } else {
      this.formRecord = {};
      this.formVisible = true;
      this.formLoading = false;
    }
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
    this.record = {};
    this.signVisible = true;
    this.signLoading = true;
    const reqId = ++this._signRequestId;
    http.get(`/api/department-duty-log/records/${record.id}/`)
      .then(data => {
        if (reqId !== this._signRequestId) return; // 丢弃过期响应
        this.record = data;
        this.signLoading = false;
      })
      .catch(() => {
        if (reqId !== this._signRequestId) return;
        this.signVisible = false;
        this.signLoading = false;
      });
  }

  @action.bound
  showReturn(record) {
    this.record = record;
    this.returnVisible = true;
  }

  /**
   * 拉取指定月份的已有已签署值班日志日期，结果缓存到 dutyDatesByMonth。
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
   * 判断某日期是否已有已签署值班日志。无缓存时返回 false（同步），
   * 调用方应先 fetchDutyDatesByMonth 把当前面板月份数据拉到。
   */
  hasDutyDate(dateStr) {
    const [y, m] = dateStr.split('-');
    const key = `${y}-${m}`;
    const set = this.dutyDatesByMonth[key];
    return !!(set && set.has(dateStr));
  }

  /**
   * 失效指定月份的日期缓存。不传参数时清空全部缓存。
   * 用于 CRUD 成功后刷新日历底纹。
   */
  @action.bound
  invalidateDutyDatesCache(months) {
    if (!months || months.length === 0) {
      this.dutyDatesByMonth = {};
      return;
    }
    const next = {...this.dutyDatesByMonth};
    for (const m of months) delete next[m];
    this.dutyDatesByMonth = next;
  }
}

export default new DepartmentDutyLogStore();
