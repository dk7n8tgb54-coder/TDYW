/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http, includes } from 'libs';

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

  @observable f_datetime;
  @observable f_report_dept;
  @observable f_interference_type;
  @observable f_phenomenon;

  get dataSource() {
    let data = this.records
    if (this.f_datetime && Array.isArray(this.f_datetime) && this.f_datetime.length === 2) {
      const startDate = this.f_datetime[0];
      const endDate = this.f_datetime[1];
      data = data.filter(x => {
        const itemDate = x.datetime ? x.datetime.substring(0, 10) : '';
        return itemDate >= startDate && itemDate <= endDate;
      });
    }
    if (this.f_report_dept) data = data.filter(x => includes(x.report_dept, this.f_report_dept))
    if (this.f_interference_type) data = data.filter(x => includes(x.interference_type, this.f_interference_type))
    if (this.f_phenomenon) data = data.filter(x => includes(x.phenomenon, this.f_phenomenon))
    return data
  }

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize
    };
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
}

export default new Store()
