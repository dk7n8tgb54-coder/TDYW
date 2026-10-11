/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行与故障记录状态管理（MobX, legacy decorators）。
 * 2026-10-11 合并改造：原 faultStore 与 runtimeRecord/store 合并为统一 Store，
 * 一张统一主表承载 日常运行/异常事件/正式故障 三类记录。
 * 业务关联一律使用系统 ID；成功提示等待后端真实成功（http.js 拦截器统一提示
 * error，业务代码不重复提示）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from '../constants';

class OperationRecordStore {
  // ========== 列表 ==========
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // ========== 筛选条件 ==========
  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_system = undefined;
  @observable f_category = undefined;
  @observable f_record_type = undefined;
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
  // 详情可能被多个入口并发刷新；只接受最后一次响应。
  detailRequestSeq = 0;
  // 详情页签受控（列表"进展数"列点击可直达进展页签）
  @observable activeTab = 'basic';

  // ========== 统一进展 ==========
  @observable progressRecords = [];
  // 进展列表接口返回的 total（详情打开时已随列表一并请求，详情"进展概览"
  // 直接复用，不额外发请求）
  @observable progressTotal = 0;
  @observable isProgressFetching = false;
  progressRequestSeq = 0;

  // ========== 附件 ==========
  @observable attachments = [];

  // ========== 动作执行中 ==========
  @observable isActionSubmitting = false;

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_system = undefined;
    this.f_category = undefined;
    this.f_record_type = undefined;
    this.f_occurred_range = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
    if (this.f_category) params.category = this.f_category;
    if (this.f_record_type) params.record_type = this.f_record_type;
    if (this.f_occurred_range && this.f_occurred_range.length === 2) {
      params.occurred_from = this.f_occurred_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.f_occurred_range[1].format('YYYY-MM-DD HH:mm');
    }
    return http.get(`${API_PREFIX}/records/`, {params})
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
    return http.get(`${API_PREFIX}/records/candidate-systems/`)
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
      ? http.put(`${API_PREFIX}/records/${this.record.id}/`, formData)
      : http.post(`${API_PREFIX}/records/`, formData);
    return request
      .then(action(() => {
        this.formVisible = false;
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  setActiveTab = action((tab) => {
    this.activeTab = tab;
  });

  showDetail = action((recordOrId, tab = 'basic') => {
    // 支持对象或纯 ID（系统详情页签/跨页跳转直达详情）。
    this.detailId = typeof recordOrId === 'object' ? recordOrId.id : recordOrId;
    this.detail = typeof recordOrId === 'object' ? recordOrId : {};
    this.detailVisible = true;
    this.activeTab = tab;
    this.progressRecords = [];
    this.progressTotal = 0;
    this.attachments = [];
    this.fetchDetail();
    this.fetchProgressRecords();
    this.fetchAttachments();
  });

  closeDetail = action(() => {
    this.detailVisible = false;
    this.detailId = null;
  });

  fetchDetail = () => {
    const requestSeq = ++this.detailRequestSeq;
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX}/records/${this.detailId}/`)
      .then(action(res => {
        // http 拦截器已解包 json_response 的 data 层，res 即详情本体
        if (requestSeq === this.detailRequestSeq) {
          this.detail = res;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.detailRequestSeq) {
          this.isDetailFetching = false;
        }
      }));
  };

  fetchDetailById = (id) => {
    // 与 fetchDetail 一致：resolve 详情本体，供编辑表单回填
    return http.get(`${API_PREFIX}/records/${id}/`);
  };

  fetchProgressRecords = () => {
    if (!this.detailId) return Promise.resolve();
    const requestSeq = ++this.progressRequestSeq;
    this.isProgressFetching = true;
    return http.get(`${API_PREFIX}/records/${this.detailId}/progress/`)
      .then(action(res => {
        if (requestSeq === this.progressRequestSeq) {
          this.progressRecords = res.data || [];
          this.progressTotal = res.total;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.progressRequestSeq) {
          this.isProgressFetching = false;
        }
      }));
  };

  fetchAttachments = () => {
    if (!this.detailId) return Promise.resolve();
    return http.get(`${API_PREFIX}/records/${this.detailId}/attachments/`)
      .then(action(res => {
        this.attachments = res.data || [];
      }))
      .catch(action(() => {}));
  };

  // ========== 状态动作（成功后重新获取真实数据） ==========
  _refreshAfterAction = () => {
    this.fetchDetail();
    this.fetchProgressRecords();
    this.fetchRecords();
  };

  _postAction = (path, formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/records/${this.detailId}/${path}/`, formData || {})
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // 完成跟进：跟进中 → 已完成（异常事件，可重新跟进）
  completeFollowUp = (formData) => this._postAction('complete', formData);

  // 认定正式故障：异常事件在原记录上认定（类型原地变更，不创建第二张单）
  identifyFault = (formData) => this._postAction('identify-fault', formData);

  // 确认恢复并结案：处置中 → 已关闭（正式故障，须同时具备 recover+close 权限）
  confirmRecoverAndClose = (formData) => this._postAction('recover', formData);

  // 撤销故障登记：处置中 → 已撤销（原因必填留痕）
  cancelRecord = (formData) => this._postAction('cancel', formData);

  // 原因分析专用保存（正式故障处置中）
  saveReasonAnalysis = (formData) => {
    this.isActionSubmitting = true;
    return http.put(`${API_PREFIX}/records/${this.detailId}/reason-analysis/`, formData)
      .then(action(() => this.fetchDetail()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // 删除记录（仅日常运行；成功后关闭详情并刷新列表真实数据）
  deleteRecord = () => {
    this.isActionSubmitting = true;
    return http.delete(`${API_PREFIX}/records/${this.detailId}/`)
      .then(action(() => {
        this.closeDetail();
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  addProgressRecord = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/records/${this.detailId}/progress/`, formData)
      // 追加进展即"跟进"动作：异常事件保存首条进展后进入跟进中、已完成追加
      // 进展重新跟进；日常运行仅补充留痕不改状态，成功后全量刷新详情/进展/
      // 列表真实数据，调用方在完成后关闭弹窗
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  correctProgressRecord = (recordId, formData) => {
    this.isActionSubmitting = true;
    return http.put(
      `${API_PREFIX}/records/${this.detailId}/progress/${recordId}/`, formData)
      .then(action(() => this.fetchProgressRecords()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // ========== 系统详情"运行与故障记录"页签 ==========
  @observable systemRecords = [];
  @observable systemRecordsTotal = 0;
  @observable systemLatestOccurredAt = null;
  @observable isSystemRecordsFetching = false;

  fetchSystemRecords = (systemId, params) => {
    this.isSystemRecordsFetching = true;
    const request = params && Object.keys(params).length
      ? http.get(`${API_PREFIX}/systems/${systemId}/records/`, {params})
      : http.get(`${API_PREFIX}/systems/${systemId}/records/`);
    return request
      .then(action(res => {
        this.systemRecords = res.data || [];
        this.systemRecordsTotal = res.total || 0;
        this.systemLatestOccurredAt = res.latest_occurred_at;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isSystemRecordsFetching = false;
      }));
  };

  // ========== 待办列表 ==========
  // 只含跟进中的异常事件记录，按最近更新优先
  @observable todoRecords = [];
  @observable isTodoFetching = false;
  todoRequestSeq = 0;

  fetchTodoRecords = () => {
    const requestSeq = ++this.todoRequestSeq;
    this.isTodoFetching = true;
    return http.get(`${API_PREFIX}/records/todo/`)
      .then(action(res => {
        if (requestSeq === this.todoRequestSeq) {
          this.todoRecords = res.data || [];
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isTodoFetching = false;
      }));
  };

  // ========== 统计 ==========
  @observable statistics = null;
  @observable isStatisticsFetching = false;
  statisticsRequestSeq = 0;
  @observable f_stats_range = undefined;
  // 统计口径按记录类型筛选（未传时后端统计全部类型）
  @observable f_stats_record_type = undefined;

  fetchStatistics = () => {
    const requestSeq = ++this.statisticsRequestSeq;
    this.isStatisticsFetching = true;
    const params = {};
    if (this.f_stats_record_type) params.record_type = this.f_stats_record_type;
    if (this.f_stats_range && this.f_stats_range.length === 2) {
      params.occurred_from = this.f_stats_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.f_stats_range[1].format('YYYY-MM-DD HH:mm');
    }
    return http.get(`${API_PREFIX}/records/statistics/`, {params})
      .then(action(res => {
        if (requestSeq === this.statisticsRequestSeq) {
          // http 拦截器已剥外层 data：res 即统计对象本体
          this.statistics = res;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isStatisticsFetching = false;
      }));
  };
}

export default new OperationRecordStore();
