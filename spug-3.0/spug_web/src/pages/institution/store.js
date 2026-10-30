/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import { observable, action } from 'mobx';
import { http } from 'libs';

class Store {
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable pageNum = 1;
  @observable pageSize = 20;
  @observable formVisible = false;
  @observable categoryVisible = false;
  @observable record = {};

  @observable categories = [];
  @observable f_keyword = undefined;
  @observable f_category_id = undefined;
  @observable f_owner_type = undefined;
  @observable f_status = undefined;

  @action.bound
  fetchRecords() {
    this.isFetching = true;
    const params = {page: this.pageNum, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_category_id) params.category_id = this.f_category_id;
    if (this.f_owner_type) params.owner_type = this.f_owner_type;
    if (this.f_status) params.status = this.f_status;
    return http.get('/api/institution/manuals/', {params})
      .then(data => {
        this.records = data.items || [];
        this.total = data.total || 0;
      })
      .finally(() => this.isFetching = false);
  }

  @action.bound
  fetchCategories() {
    return http.get('/api/institution/categories/')
      .then(data => this.categories = data || []);
  }

  @action.bound
  setPage(page, pageSize) {
    this.pageNum = page;
    this.pageSize = pageSize;
    this.fetchRecords();
  }

  @action.bound
  showForm(record) {
    this.record = record || {};
    this.formVisible = true;
  }

  @action.bound
  showCategories() {
    this.categoryVisible = true;
  }
}

export default new Store();
