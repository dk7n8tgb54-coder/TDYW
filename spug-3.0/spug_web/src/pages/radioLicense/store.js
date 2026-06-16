/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

class Store {
  // ========== 数据列表 ==========
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable pageNum = 1;
  @observable pageSize = 20;

  // ========== 表单弹窗 ==========
  @observable formVisible = false;
  @observable detailVisible = false;
  @observable record = {};

  // ========== 筛选条件 ==========
  @observable f_station_name = undefined;
  @observable f_purpose = undefined;
  @observable f_status = undefined;
  @observable f_valid_to_range = undefined;

  // ========== 状态选项 ==========
  statusOptions = [
    {value: 'normal', label: '正常'},
    {value: 'expiring', label: '即将到期'},
    {value: 'expired', label: '已过期'},
  ];

  // ========== 频率单位选项 ==========
  frequencyUnitOptions = [
    {value: 'MHz', label: 'MHz'},
    {value: 'kHz', label: 'kHz'},
    {value: 'GHz', label: 'GHz'},
  ];

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize,
    };
    if (this.f_station_name) params.station_name = this.f_station_name;
    if (this.f_purpose) params.purpose = this.f_purpose;
    if (this.f_status) params.status = this.f_status;
    if (this.f_valid_to_range && this.f_valid_to_range.length === 2) {
      params.valid_to_start = this.f_valid_to_range[0];
      params.valid_to_end = this.f_valid_to_range[1];
    }

    http.get('/api/radio-license/', { params })
      .then(({records, total, page, page_size}) => {
        this.records = records;
        this.total = total || 0;
        this.pageNum = page || this.pageNum;
        this.pageSize = page_size || this.pageSize;
      })
      .catch(e => {
        console.error('[电台执照] 获取列表失败:', e);
      })
      .finally(() => this.isFetching = false)
  };

  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = {...info};
  };

  showDetail = (info = {}) => {
    this.detailVisible = true;
    this.record = {...info};
  };
}

export default new Store()
