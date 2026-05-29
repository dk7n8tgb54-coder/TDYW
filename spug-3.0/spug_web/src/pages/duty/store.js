/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

class Store {
  @observable records = [];
  @observable dutyPersons = [];
  @observable departments = [];
  @observable record = {};
  @observable isFetching = false;
  @observable formVisible = false;
  @observable detailVisible = false;

  @observable f_duty_person;
  @observable f_department;
  @observable f_start_date;
  @observable f_end_date;

  get dataSource() {
    let data = this.records
    if (this.f_duty_person) data = data.filter(x => x.duty_person === this.f_duty_person)
    if (this.f_department) data = data.filter(x => x.department === this.f_department)
    if (this.f_start_date) data = data.filter(x => x.duty_date >= this.f_start_date)
    if (this.f_end_date) data = data.filter(x => x.duty_date <= this.f_end_date)
    return data
  }

  fetchRecords = () => {
    this.isFetching = true;
    http.get('/api/duty/duty/')
      .then(({duty_persons, departments, records}) => {
        this.records = records;
        this.dutyPersons = duty_persons;
        this.departments = departments;
      })
      .finally(() => this.isFetching = false)
  };

  showForm = (info = {}, isViewMode = false) => {
    this.formVisible = true;
    this.record = {...info, isViewMode};
  }

  showDetail = (info) => {
    this.detailVisible = true;
    this.record = info;
  }
}

export default new Store()
