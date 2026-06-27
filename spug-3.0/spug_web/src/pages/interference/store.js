/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

class Store {
  @observable records = [];
  @observable interferenceTypes = [];
  @observable reportDepts = [];
  @observable record = {};
  @observable isFetching = false;
  @observable formVisible = false;
  @observable pageNum = 1;
  @observable pageSize = 10;
  @observable total = 0;

  // 筛选条件
  @observable f_frequency;
  @observable f_report_dept;
  @observable f_interference_type;
  @observable f_datetime = [];

  get dataSource() {
    // 筛选已由后端完成，直接返回当前页记录
    return this.records;
  }

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize
    };
    if (this.f_frequency) params.frequency = this.f_frequency;
    if (this.f_report_dept) params.report_dept = this.f_report_dept;
    if (this.f_interference_type) params.interference_type = this.f_interference_type;
    if (Array.isArray(this.f_datetime) && this.f_datetime.length === 2) {
      params.start_date = this.f_datetime[0];
      params.end_date = this.f_datetime[1];
    }
    http.get('/api/interference/', { params })
      .then(({interference_types, report_depts, records, total, page, page_size}) => {
        this.records = records;
        this.interferenceTypes = interference_types;
        this.reportDepts = report_depts;
        this.total = total || 0;
        // 更新分页信息
        this.pageNum = page || this.pageNum;
        this.pageSize = page_size || this.pageSize;
      })
      .catch(e => {
        // 【优化】添加错误提示
        console.error('[干扰] 获取干扰记录失败:', e);
      })
      .finally(() => this.isFetching = false)
  };

  showForm = (info = {}, isViewMode = false) => {
    this.formVisible = true;
    this.record = {...info, isViewMode};
  }

  resetFilter = () => {
    this.f_frequency = null;
    this.f_report_dept = null;
    this.f_datetime = [];
    this.f_interference_type = null;
    this.pageNum = 1;
    this.fetchRecords();
  };

  getExportParams = () => {
    const params = {};
    if (this.f_frequency) params.frequency = this.f_frequency;
    if (this.f_report_dept) params.report_dept = this.f_report_dept;
    if (this.f_interference_type) params.interference_type = this.f_interference_type;
    if (Array.isArray(this.f_datetime) && this.f_datetime.length === 2) {
      params.start_date = this.f_datetime[0];
      params.end_date = this.f_datetime[1];
    }
    return params;
  };
}

export default new Store()
