/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录状态管理（MobX, legacy decorators）。
 * 业务关联一律使用系统 ID；成功提示等待后端真实成功（http.js 拦截器统一提示 error，
 * 业务代码不重复提示）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from '../constants';

class RuntimeRecordStore {
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
  @observable f_follow = undefined;
  @observable f_importance = undefined;
  @observable f_impact = undefined;
  @observable f_category = undefined;
  @observable f_repeated = undefined;
  @observable f_occurred_range = undefined;

  // ========== 表单 ==========
  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;

  // ========== 系统候选项 ==========
  @observable systems = [];

  // ========== 详情抽屉 ==========
  @observable detailVisible = false;
  @observable detailId = null;
  @observable detail = {};
  @observable isDetailFetching = false;
  // 详情可能被多个入口并发刷新；只接受最后一次响应。
  detailRequestSeq = 0;

  // ========== 处理进展 ==========
  @observable progressRecords = [];
  // 进展列表接口返回的 total（详情打开时已随列表一并请求，详情"处理概览"
  // 直接复用，不额外发请求；未取到 total 时组件回落用已取到的列表长度）
  @observable progressTotal = 0;
  @observable isProgressFetching = false;
  progressRequestSeq = 0;

  // ========== 附件 ==========
  @observable attachments = [];

  // ========== 动作执行中 ==========
  @observable isActionSubmitting = false;

  // ========== 第二版：研判弹窗 ==========
  @observable triageVisible = false;

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_system = undefined;
    this.f_follow = undefined;
    this.f_importance = undefined;
    this.f_impact = undefined;
    this.f_category = undefined;
    this.f_repeated = undefined;
    this.f_occurred_range = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
    if (this.f_follow !== undefined && this.f_follow !== null) {
      params.needs_follow_up = this.f_follow ? 'yes' : 'no';
    }
    if (this.f_importance) params.importance = this.f_importance;
    if (this.f_impact) params.impact = this.f_impact;
    if (this.f_category) params.category = this.f_category;
    if (this.f_repeated !== undefined && this.f_repeated !== null) {
      params.repeated = this.f_repeated ? 'yes' : 'no';
    }
    if (this.f_occurred_range && this.f_occurred_range.length === 2) {
      params.occurred_from = this.f_occurred_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.f_occurred_range[1].format('YYYY-MM-DD HH:mm');
    }
    return http.get(`${API_PREFIX}/runtime-records/`, {params})
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
      ? http.put(`${API_PREFIX}/runtime-records/${this.record.id}/`, formData)
      : http.post(`${API_PREFIX}/runtime-records/`, formData);
    return request
      .then(action(() => {
        this.formVisible = false;
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  showDetail = action((recordOrId) => {
    // 支持对象或纯 ID（系统详情页签/深链接跳转直达详情）。
    this.detailId = typeof recordOrId === 'object' ? recordOrId.id : recordOrId;
    this.detail = typeof recordOrId === 'object' ? recordOrId : {};
    this.detailVisible = true;
    this.progressRecords = [];
    this.progressTotal = 0;
    this.attachments = [];
    this.duplicateLinks = [];
    this.similarRecords = [];
    this.fetchDetail();
    this.fetchProgressRecords();
    this.fetchAttachments();
    this.fetchDuplicateLinks();
    this.fetchSimilarRecords();
  });

  closeDetail = action(() => {
    this.detailVisible = false;
    this.detailId = null;
  });

  fetchDetail = () => {
    const requestSeq = ++this.detailRequestSeq;
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX}/runtime-records/${this.detailId}/`)
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
    return http.get(`${API_PREFIX}/runtime-records/${id}/`);
  };

  fetchProgressRecords = () => {
    if (!this.detailId) return Promise.resolve();
    const requestSeq = ++this.progressRequestSeq;
    this.isProgressFetching = true;
    return http.get(`${API_PREFIX}/runtime-records/${this.detailId}/progress/`)
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
    return http.get(`${API_PREFIX}/runtime-records/${this.detailId}/attachments/`)
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
    return http.post(`${API_PREFIX}/runtime-records/${this.detailId}/${path}/`, formData || {})
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  markFollowUp = (extra) => this._postAction('follow-up', extra);

  resolveRecord = (formData) => this._postAction('resolve', formData);

  closeRecord = (formData) => this._postAction('close', formData);

  markImportant = (formData) => this._postAction('mark-important', formData);

  // ========== 第二版：研判 / 无需跟进 / 重复标记 ==========
  submitTriage = (formData) => this._postAction('triage', formData);

  markNoFollowUp = () => this._postAction('no-follow-up');

  markRepeated = (isRepeated) => this._postAction('mark-repeated', {is_repeated: isRepeated});

  // ========== 第二版：重复问题关联 ==========
  @observable duplicateLinks = [];
  @observable isLinksFetching = false;
  linksRequestSeq = 0;

  // 相似记录查询
  @observable similarRecords = [];
  @observable isSimilarFetching = false;
  similarRequestSeq = 0;

  fetchDuplicateLinks = () => {
    if (!this.detailId) return Promise.resolve();
    const requestSeq = ++this.linksRequestSeq;
    this.isLinksFetching = true;
    return http.get(`${API_PREFIX}/runtime-records/${this.detailId}/duplicate-links/`)
      .then(action(res => {
        if (requestSeq === this.linksRequestSeq) {
          this.duplicateLinks = res.data || [];
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.linksRequestSeq) {
          this.isLinksFetching = false;
        }
      }));
  };

  linkDuplicate = (duplicateId, note) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/runtime-records/${this.detailId}/duplicate-links/`,
      {duplicate_id: duplicateId, note: note || ''})
      .then(action(() => this.fetchDuplicateLinks()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  unlinkDuplicate = (linkId) => {
    this.isActionSubmitting = true;
    return http.delete(`${API_PREFIX}/runtime-records/${this.detailId}/duplicate-links/${linkId}/`)
      .then(action(() => this.fetchDuplicateLinks()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  fetchSimilarRecords = () => {
    if (!this.detailId) return Promise.resolve();
    const requestSeq = ++this.similarRequestSeq;
    this.isSimilarFetching = true;
    return http.get(`${API_PREFIX}/runtime-records/${this.detailId}/similar/`)
      .then(action(res => {
        if (requestSeq === this.similarRequestSeq) {
          this.similarRecords = res.data || [];
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.similarRequestSeq) {
          this.isSimilarFetching = false;
        }
      }));
  };

  convertToFault = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/runtime-records/${this.detailId}/convert-to-fault/`, formData || {})
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  addProgressRecord = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/runtime-records/${this.detailId}/progress/`, formData)
      // 追加进展只改变时间线；返回列表刷新 Promise，调用方在真实列表完成后再关闭弹窗。
      .then(action(() => this.fetchProgressRecords()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  correctProgressRecord = (recordId, formData) => {
    this.isActionSubmitting = true;
    return http.put(
      `${API_PREFIX}/runtime-records/${this.detailId}/progress/${recordId}/`, formData)
      .then(action(() => this.fetchProgressRecords()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // ========== 系统详情运行记录页签 ==========
  @observable systemRecords = [];
  @observable systemRecordsTotal = 0;
  @observable systemLatestOccurredAt = null;
  @observable isSystemRecordsFetching = false;

  fetchSystemRecords = (systemId, params) => {
    this.isSystemRecordsFetching = true;
    // 无筛选参数时不携带 config，保持与旧调用形态一致
    const request = params && Object.keys(params).length
      ? http.get(`${API_PREFIX}/systems/${systemId}/runtime-records/`, {params})
      : http.get(`${API_PREFIX}/systems/${systemId}/runtime-records/`);
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

  // ========== 第二版：待办列表 ==========
  @observable todoRecords = [];
  @observable todoOverdueCount = 0;
  @observable isTodoFetching = false;
  todoRequestSeq = 0;
  // 待办筛选：overdue 超期 / follow_up_name 指定跟进人 / order=planned|recent
  @observable f_todo_overdue = undefined;
  @observable f_todo_follow_up_name = undefined;
  @observable f_todo_order = 'planned';

  @action resetTodoFilter = () => {
    this.f_todo_overdue = undefined;
    this.f_todo_follow_up_name = undefined;
    this.f_todo_order = 'planned';
  };

  fetchTodoRecords = () => {
    const requestSeq = ++this.todoRequestSeq;
    this.isTodoFetching = true;
    const params = {};
    if (this.f_todo_overdue) params.overdue = 'yes';
    if (this.f_todo_follow_up_name) params.follow_up_name = this.f_todo_follow_up_name;
    if (this.f_todo_order) params.order = this.f_todo_order;
    return http.get(`${API_PREFIX}/runtime-records/todo/`, {params})
      .then(action(res => {
        if (requestSeq === this.todoRequestSeq) {
          this.todoRecords = res.data || [];
          this.todoOverdueCount = res.overdue_count || 0;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.todoRequestSeq) {
          this.isTodoFetching = false;
        }
      }));
  };

  // ========== 第二版：统计 ==========
  @observable statistics = null;
  @observable isStatisticsFetching = false;
  statisticsRequestSeq = 0;
  @observable f_stats_range = undefined;

  fetchStatistics = () => {
    const requestSeq = ++this.statisticsRequestSeq;
    this.isStatisticsFetching = true;
    const params = {};
    if (this.f_stats_range && this.f_stats_range.length === 2) {
      params.occurred_from = this.f_stats_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.f_stats_range[1].format('YYYY-MM-DD HH:mm');
    }
    return http.get(`${API_PREFIX}/runtime-records/statistics/`, {params})
      .then(action(res => {
        if (requestSeq === this.statisticsRequestSeq) {
          // http 拦截器已剥外层 data：res 即统计对象本体
          this.statistics = res;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (requestSeq === this.statisticsRequestSeq) {
          this.isStatisticsFetching = false;
        }
      }));
  };
}

export default new RuntimeRecordStore();
