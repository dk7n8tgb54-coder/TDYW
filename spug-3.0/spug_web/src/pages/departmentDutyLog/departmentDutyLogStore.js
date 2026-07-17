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
  @observable signVisible = false;
  @observable voidVisible = false;
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

  // 常量
  statusOptions = [
    {value: 'draft', label: '草稿'},
    {value: 'signed', label: '已签署'},
    {value: 'void', label: '已作废'},
  ];

  statusTagMap = {
    draft: {color: 'default', text: '草稿'},
    signed: {color: 'green', text: '已签署'},
    void: {color: 'red', text: '已作废'},
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
    this.record = record;
    this.detailVisible = true;
  }

  @action.bound
  showSign(record) {
    this.record = record;
    this.signVisible = true;
  }

  @action.bound
  showVoid(record) {
    this.record = record;
    this.voidVisible = true;
  }
}

export default new DepartmentDutyLogStore();
