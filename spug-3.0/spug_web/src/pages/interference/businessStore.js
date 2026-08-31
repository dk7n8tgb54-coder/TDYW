/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 干扰管理双业务类型（地面/空中）列表页共享 Store 工厂。
 * 两类业务列表行为一致，仅后端 API 路径不同。
 */
import { observable } from "mobx";
import { http } from 'libs';

export function createBusinessStore(apiPath) {
  class Store {
    @observable records = [];
    @observable record = {};
    @observable isFetching = false;
    @observable formVisible = false;
    @observable pageNum = 1;
    @observable pageSize = 10;
    @observable total = 0;

    // 筛选条件
    @observable f_flight_number;
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
      if (this.f_flight_number) params.flight_number = this.f_flight_number;
      if (Array.isArray(this.f_datetime) && this.f_datetime.length === 2) {
        params.start_date = this.f_datetime[0];
        params.end_date = this.f_datetime[1];
      }
      return http.get(apiPath, { params })
        .then(({records, total, page, page_size}) => {
          this.records = records;
          this.total = total || 0;
          this.pageNum = page || this.pageNum;
          this.pageSize = page_size || this.pageSize;
        })
        .finally(() => this.isFetching = false)
    };

    showForm = (info = {}, isViewMode = false) => {
      this.formVisible = true;
      this.record = {...info, isViewMode};
    }

    resetFilter = () => {
      this.f_flight_number = null;
      this.f_datetime = [];
      this.pageNum = 1;
      this.fetchRecords();
    };

    getExportParams = () => {
      const params = {};
      if (this.f_flight_number) params.flight_number = this.f_flight_number;
      if (Array.isArray(this.f_datetime) && this.f_datetime.length === 2) {
        params.start_date = this.f_datetime[0];
        params.end_date = this.f_datetime[1];
      }
      return params;
    };
  }

  return new Store();
}
