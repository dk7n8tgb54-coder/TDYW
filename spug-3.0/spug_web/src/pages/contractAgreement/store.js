/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from 'mobx';
import { http, syncAttachmentCount } from 'libs';

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
  @observable f_contract_no = undefined;
  @observable f_contract_type = undefined;
  @observable f_status = undefined;
  @observable f_signing_party = undefined;
  @observable f_has_fee = undefined;
  @observable f_valid_end_range = undefined;

  // 合同名称/合同编号/签约方文本输入草稿（输入中、未执行，2026-10-20 筛选
  // 交互统一）：Input 绑定草稿，查询按钮/回车提交后才转正为 f_*，避免
  // "输入未查询"的文本混入类型/状态/费用下拉与截止日期触发的即时查询
  @observable input_contract_name = '';
  @observable input_contract_no = '';
  @observable input_signing_party = '';

  // 文本草稿输入（三个文本条件共用一套草稿→已执行口径）
  setContractNameInput = (value) => {
    this.input_contract_name = value;
  };

  setContractNoInput = (value) => {
    this.input_contract_no = value;
  };

  setSigningPartyInput = (value) => {
    this.input_signing_party = value;
  };

  // 查询按钮/文本框回车共用：提交全部文本草稿为已执行条件，回到第 1 页刷新
  commitFilters = () => {
    this.f_contract_name = this.input_contract_name || undefined;
    this.f_contract_no = this.input_contract_no || undefined;
    this.f_signing_party = this.input_signing_party || undefined;
    this.pageNum = 1;
    return this.fetchRecords();
  };

  // 重置：清空常驻与折叠区全部条件及文本草稿，回到第 1 页（刷新由调用方执行）
  resetFilter = () => {
    this.input_contract_name = '';
    this.input_contract_no = '';
    this.input_signing_party = '';
    this.f_contract_name = undefined;
    this.f_contract_no = undefined;
    this.f_contract_type = undefined;
    this.f_status = undefined;
    this.f_signing_party = undefined;
    this.f_has_fee = undefined;
    this.f_valid_end_range = undefined;
    this.pageNum = 1;
  };

  contractTypeOptions = [
    {value: 'device_purchase', label: '设备采购合同'},
    {value: 'info_access', label: '信息引接合同'},
    {value: 'service_guarantee', label: '服务保障协议'},
  ];

  statusOptions = [
    {value: 'normal', label: '正常'},
    {value: 'expiring', label: '即将到期'},
    {value: 'expired', label: '已关闭'},
    {value: 'long_term', label: '长期有效'},
  ];

  // ========== 可选责任人列表 ==========
  @observable responsibleUsers = [];
  @observable responsibleUsersLoaded = false;
  // 拉取责任人列表时使用的登录 token（非响应式，仅作缓存指纹）
  _responsibleUsersToken = null;

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize,
    };
    if (this.f_contract_name) params.contract_name = this.f_contract_name;
    if (this.f_contract_no) params.contract_no = this.f_contract_no;
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

  // 附件数量变化（上传/删除）时实时回写列表行与当前记录，无需刷新页面
  updateAttachmentCount = (id, count) => syncAttachmentCount(this, id, count);

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

  // 拉取可选责任人列表（懒加载，首次进入表单时调用）。
  // 本 store 为模块级单例，同一浏览器切换账号（登出不刷新页面）后仍在内存，
  // 记录拉取时的登录 token，token 变化即强制重拉，避免残留上一账号租户的责任人。
  fetchResponsibleUsers = () => {
    const token = sessionStorage.getItem('token');
    if (this.responsibleUsersLoaded && token === this._responsibleUsersToken) {
      return Promise.resolve(this.responsibleUsers);
    }
    return http.get('/api/contract-agreement/responsible-users/')
      .then(res => {
        this.responsibleUsers = res || [];
        this.responsibleUsersLoaded = true;
        this._responsibleUsersToken = token;
        return this.responsibleUsers;
      })
      .catch(e => {
        console.error('[合同协议] 获取责任人列表失败:', e);
        return [];
      });
  };
}

export default new Store();
