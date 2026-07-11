/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from 'mobx';
import { http } from 'libs';

class Store {
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable pageNum = 1;
  @observable pageSize = 20;

  @observable formVisible = false;
  @observable detailVisible = false;
  @observable record = {};

  @observable f_contract_name = undefined;
  @observable f_contract_type = undefined;
  @observable f_status = undefined;
  @observable f_signing_party = undefined;
  @observable f_has_fee = undefined;
  @observable f_valid_end_range = undefined;

  contractTypeOptions = [
    {value: 'device_purchase', label: '设备采购合同'},
    {value: 'info_access', label: '信息引接合同'},
    {value: 'service_guarantee', label: '服务保障协议'},
  ];

  statusOptions = [
    {value: 'normal', label: '正常'},
    {value: 'expiring', label: '即将到期'},
    {value: 'expired', label: '已过期'},
  ];

  // ========== 可选责任人列表 ==========
  @observable responsibleUsers = [];
  @observable responsibleUsersLoaded = false;

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize,
    };
    if (this.f_contract_name) params.contract_name = this.f_contract_name;
    if (this.f_contract_type) params.contract_type = this.f_contract_type;
    if (this.f_status) params.status = this.f_status;
    if (this.f_signing_party) params.signing_party = this.f_signing_party;
    if (this.f_has_fee !== undefined) params.has_fee = this.f_has_fee;
    if (this.f_valid_end_range && this.f_valid_end_range.length === 2) {
      params.valid_end_from = this.f_valid_end_range[0];
      params.valid_end_to = this.f_valid_end_range[1];
    }

    http.get('/api/contract-agreement/', {params})
      .then(({records, total, page, page_size}) => {
        this.records = records || [];
        this.total = total || 0;
        this.pageNum = page || this.pageNum;
        this.pageSize = page_size || this.pageSize;
      })
      .catch(e => {
        console.error('[合同协议] 获取列表失败:', e);
      })
      .finally(() => this.isFetching = false);
  };

  fetchDetail = (id) => {
    if (!id) return Promise.resolve(null);
    return http.get(`/api/contract-agreement/${id}/`)
      .then(data => {
        this.showDetail(data);
        return data;
      })
      .catch(e => {
        console.error('[合同协议] 获取详情失败:', e);
        return null;
      });
  };

  showForm = (info = {}) => {
    this.formVisible = true;
    this.detailVisible = false;
    this.record = {...info};
  };

  showDetail = (info = {}) => {
    this.detailVisible = true;
    this.formVisible = false;
    this.record = {...info};
  };

  // 拉取可选责任人列表（懒加载，首次进入表单时调用）
  fetchResponsibleUsers = () => {
    if (this.responsibleUsersLoaded) return Promise.resolve(this.responsibleUsers);
    return http.get('/api/contract-agreement/responsible-users/')
      .then(res => {
        this.responsibleUsers = res || [];
        this.responsibleUsersLoaded = true;
        return this.responsibleUsers;
      })
      .catch(e => {
        console.error('[合同协议] 获取责任人列表失败:', e);
        return [];
      });
  };
}

export default new Store();
