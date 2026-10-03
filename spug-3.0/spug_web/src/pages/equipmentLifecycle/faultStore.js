/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障处置状态管理（MobX, legacy decorators）。
 * 业务关联一律使用系统 ID；成功提示等待后端真实成功（http.js 拦截器统一提示 error）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from './constants';

class FaultStore {
  // ========== 故障列表 ==========
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // ========== 筛选条件 ==========
  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_system = undefined;
  @observable f_occurred_range = undefined;

  // ========== 表单 ==========
  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;

  // ========== 系统候选项 ==========
  @observable systems = [];

  // ========== 详情窗口 ==========
  @observable detailVisible = false;
  @observable detailId = null;
  @observable detail = {};
  @observable isDetailFetching = false;
  // 当前激活页签（受控）：列表"处理进展"列点击直达处理进展页签，
  // 基本信息"查看全部进展"同款跳转；showDetail 每次打开都会重置
  @observable activeTab = 'basic';
  // 详情可能被多个入口并发刷新（打开详情、动作后的统一刷新、重开其他故障）；
  // 只接受最后一次响应：旧响应不覆盖新数据、不提前关闭 loading。
  detailRequestSeq = 0;

  // ========== 处理进展（原处置记录） ==========
  @observable handlingRecords = [];
  // 总条数（取列表接口 total）：详情页签实时展示条数，停在基本信息页签
  // 也能看出进展是否已登记；后端默认分页 100 条，不能用数组长度代替
  @observable handlingTotal = 0;
  @observable isHandlingFetching = false;
  // 处理进展可能在详情初始请求尚未完成时再次刷新；只接受最后一次响应。
  handlingRequestSeq = 0;

  // ========== 动作执行中 ==========
  @observable isActionSubmitting = false;

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_system = undefined;
    this.f_occurred_range = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
    if (this.f_occurred_range && this.f_occurred_range.length === 2) {
      params.occurred_from = this.f_occurred_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.f_occurred_range[1].format('YYYY-MM-DD HH:mm');
    }
    return http.get(`${API_PREFIX}/faults/`, {params})
      .then(action(res => {
        this.records = res.data;
        this.total = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  fetchSystems = () => {
    return http.get(`${API_PREFIX}/faults/candidate-systems/`)
      .then(action(res => {
        this.systems = res.data;
      }))
      .catch(action(() => {}));
  };

  systemOption = (id) => {
    return this.systems.find(s => s.id === id);
  };

  showForm = action((record = {}) => {
    this.record = record;
    this.formVisible = true;
    this.fetchSystems();
  });

  submitForm = (formData) => {
    this.isSubmitting = true;
    const isEdit = !!this.record.id;
    const request = isEdit
      ? http.put(`${API_PREFIX}/faults/${this.record.id}/`, formData)
      : http.post(`${API_PREFIX}/faults/`, formData);
    return request
      .then(action(() => {
        this.formVisible = false;
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  showDetail = action((recordOrId, tab = 'basic') => {
    // 支持对象或纯 ID（跨页 ?detail= 跳转直达详情）；
    // 第二参数指定打开后定位的页签（列表"处理进展"列点击 → 'handling'）。
    // 详情与处理进展请求统一在此发起；FaultDetail 挂载时不再重复请求
    // （打开详情时的并发重复请求是旧响应覆盖新数据的竞态来源）。
    this.detailId = typeof recordOrId === 'object' ? recordOrId.id : recordOrId;
    this.detail = typeof recordOrId === 'object' ? recordOrId : {};
    this.detailVisible = true;
    this.activeTab = tab === 'handling' ? 'handling' : 'basic';
    this.handlingRecords = [];
    this.handlingTotal = 0;
    this.fetchDetail();
    this.fetchHandlingRecords();
  });

  setActiveTab = action((tab) => {
    this.activeTab = tab === 'handling' ? 'handling' : 'basic';
  });

  closeDetail = action(() => {
    this.detailVisible = false;
    this.detailId = null;
  });

  fetchDetail = ({silent} = {}) => {
    const requestSeq = ++this.detailRequestSeq;
    // silent：动作后的伴随刷新（如添加处理进展后同步概览统计），
    // 不让整个详情窗口进入全量 loading，只更新数据本身
    if (!silent) {
      this.isDetailFetching = true;
    }
    return http.get(`${API_PREFIX}/faults/${this.detailId}/`)
      .then(action(res => {
        // http 拦截器已解包 json_response 的 data 层，res 即详情本体
        if (requestSeq === this.detailRequestSeq) {
          this.detail = res;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.detailRequestSeq && !silent) {
          this.isDetailFetching = false;
        }
      }));
  };

  fetchDetailById = (id) => {
    // 与 fetchDetail 一致：resolve 详情本体，供编辑表单回填
    return http.get(`${API_PREFIX}/faults/${id}/`);
  };

  fetchHandlingRecords = () => {
    const requestSeq = ++this.handlingRequestSeq;
    this.isHandlingFetching = true;
    return http.get(`${API_PREFIX}/faults/${this.detailId}/handling-records/`)
      .then(action(res => {
        if (requestSeq === this.handlingRequestSeq) {
          this.handlingRecords = res.data || [];
          this.handlingTotal = res.total ?? (res.data || []).length;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.handlingRequestSeq) {
          this.isHandlingFetching = false;
        }
      }));
  };

  // ========== 状态动作（成功后重新获取真实数据） ==========
  // 2026-10 流程简化：无"开始处置"步骤（新建即处置中）；确认恢复与关闭
  // 故障合并为一次"确认恢复并结案"操作（recover 端点单事务）
  confirmRecoverAndClose = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/recover/`, formData)
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // 原因分析专用保存（2026-10）：详情页"补充原因分析/修改"弹窗出口，
  // 只提交原因分析字段（后端 PUT faults/{id}/reason-analysis/），不重复提交
  // 系统/发生时间等无关字段；成功后静默刷新详情（处置结果区块随新状态展示），
  // 返回刷新 Promise 供调用方在真实完成后提示并关闭弹窗
  saveReasonAnalysis = (formData) => {
    this.isActionSubmitting = true;
    return http.put(`${API_PREFIX}/faults/${this.detailId}/reason-analysis/`, formData)
      .then(action(() => this.fetchDetail({silent: true})))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  cancelFault = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/cancel/`, formData)
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  addHandlingRecord = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/faults/${this.detailId}/handling-records/`, formData)
      // 添加处理进展改变时间线，同时静默刷新详情（基本信息"处理概览"的
      // 条数/最近更新/最后记录由后端详情接口统计返回，须同步更新；
      // silent 不触发整个详情窗口的全量 loading）。返回刷新 Promise，
      // 调用方在真实刷新完成后再关闭弹窗。
      .then(action(() => Promise.all([
        this.fetchDetail({silent: true}),
        this.fetchHandlingRecords(),
      ])))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  correctHandlingRecord = (recordId, formData) => {
    this.isActionSubmitting = true;
    return http.put(
      `${API_PREFIX}/faults/${this.detailId}/handling-records/${recordId}/`, formData)
      // 更正可能修改进展内容/时间（影响"最后记录"概览），同样静默刷新详情
      .then(action(() => Promise.all([
        this.fetchDetail({silent: true}),
        this.fetchHandlingRecords(),
      ])))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  _refreshAfterAction = () => {
    this.fetchDetail();
    this.fetchHandlingRecords();
    this.fetchRecords();
  };

  // ========== 系统详情故障页签（单系统简化：只查本系统故障） ==========
  @observable systemFaults = [];
  @observable isSystemFaultsFetching = false;

  fetchSystemFaults = (systemId) => {
    this.isSystemFaultsFetching = true;
    return http.get(`${API_PREFIX}/systems/${systemId}/faults/`)
      .then(action(res => {
        this.systemFaults = res.data || [];
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isSystemFaultsFetching = false;
      }));
  };
}

export default new FaultStore();
