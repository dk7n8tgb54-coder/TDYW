/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http, includes } from 'libs';

class Store {
  @observable records = [];
  @observable systemNames = [];
  @observable record = {};
  @observable isFetching = false;
  @observable formVisible = false;

  @observable f_fault_date;
  @observable f_system_name;
  @observable f_handler;
  @observable f_fault_level;
  @observable f_export_date_range;

  get dataSource() {
    let data = this.records
    if (this.f_fault_date) data = data.filter(x => includes(x.fault_date, this.f_fault_date))
    if (this.f_system_name) data = data.filter(x => includes(x.system_name, this.f_system_name))
    if (this.f_handler) data = data.filter(x => includes(x.handler, this.f_handler))
    if (this.f_fault_level) data = data.filter(x => includes(x.fault_level, this.f_fault_level))
    return data
  }

  fetchRecords = () => {
    this.isFetching = true;
    http.get('/api/fault/faultrecord/')
      .then(({system_names, records}) => {
        this.records = records;
        this.systemNames = system_names;
      })
      .finally(() => this.isFetching = false)
  };

  showForm = (info = {}, isViewMode = false) => {
    this.formVisible = true;
    this.record = {...info, isViewMode};
  }

  getExportParams = () => {
    const params = {};
    if (this.f_system_name) params.system_name = this.f_system_name;
    if (this.f_fault_date) params.fault_date = this.f_fault_date;
    if (this.f_handler) params.f_handler = this.f_handler;
    if (this.f_fault_level) params.fault_level = this.f_fault_level;
    if (this.f_export_date_range && this.f_export_date_range.length === 2) {
      params.start_date = this.f_export_date_range[0].format('YYYY-MM-DD');
      params.end_date = this.f_export_date_range[1].format('YYYY-MM-DD');
    }
    return params;
  };
}

export default new Store()
