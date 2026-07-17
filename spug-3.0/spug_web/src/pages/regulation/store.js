/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, action } from 'mobx';
import { http } from 'libs';

class Store {
  @observable records = [];
  @observable categories = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable pageNum = 1;
  @observable pageSize = 20;

  @observable formVisible = false;
  @observable detailVisible = false;
  @observable categoryFormVisible = false;
  @observable record = {};
  @observable categoryRecord = {};

  // 筛选
  @observable f_keyword = undefined;
  @observable f_category_id = undefined;
  @observable f_biz_type = undefined;
  @observable f_status = undefined;
  @observable f_issuing_authority = undefined;

  // 常量
  statusOptions = [
    {value: 'active', label: '现行'},
    {value: 'retired', label: '已废止'},
  ];

  statusTagMap = {
    active: {color: 'green', text: '现行'},
    retired: {color: 'red', text: '已废止'},
  };

  @action.bound
  fetchRecords() {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize,
    };
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_category_id) params.category_id = this.f_category_id;
    if (this.f_biz_type) params.biz_type = this.f_biz_type;
    if (this.f_status) params.status = this.f_status;
    if (this.f_issuing_authority) params.issuing_authority = this.f_issuing_authority;

    http.get('/api/regulation/', { params })
      .then(({ items, total }) => {
        this.records = items || [];
        this.total = total || 0;
      })
      .finally(() => this.isFetching = false);
  }

  @action.bound
  fetchCategories() {
    http.get('/api/regulation/categories/tree/')
      .then(data => { this.categories = data || []; });
  }

  @action.bound
  showForm(record) {
    this.record = record || {};
    this.formVisible = true;
  }

  @action.bound
  showDetail(record) {
    this.record = record || {};
    this.detailVisible = true;
  }

  @action.bound
  showCategoryForm(record) {
    this.categoryRecord = record || {};
    this.categoryFormVisible = true;
  }
}

export default new Store();
