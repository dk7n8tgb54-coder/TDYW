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
}

export default new Store()
