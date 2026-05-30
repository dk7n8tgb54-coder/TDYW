/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from 'mobx';
import http from 'libs/http';

class Store {
  @observable records = [];
  @observable record = {};
  @observable isFetching = true;
  @observable formVisible = false;

  fetchRecords = () => {
    this.isFetching = true;
    http.get('/api/account/tenant/')
      .then(res => this.records = res)
      .finally(() => this.isFetching = false)
  };

  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = info
  }
}

export default new Store()
