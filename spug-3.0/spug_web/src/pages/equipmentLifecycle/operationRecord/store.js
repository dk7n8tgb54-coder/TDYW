/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行处置记录状态管理（MobX, legacy decorators）。
 * 2026-10-11 合并改造：原 faultStore 与 runtimeRecord/store 合并为统一 Store，
 * 一张统一主表承载 一般记录/异常事件/设备故障 三类记录。
 * 业务关联一律使用系统 ID；成功提示等待后端真实成功（http.js 拦截器统一提示
 * error，业务代码不重复提示）。
 * 2026-10-15 体验四轮：关键词输入草稿（input_keyword/sf_input_keyword）与
 * 已执行条件（f_keyword/sf_keyword）分离，查询按钮/回车提交草稿，列表取数/
 * 导出参数/联动刷新/导出范围文案一律只用已执行条件；详情加载失败置
 * detailError 显式呈现并可重试（保持当前记录与页签），详情与附件请求的
 * 旧响应/迟到失败由请求序号防护拦截，不覆盖新记录。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import {
  API_PREFIX, RECORD_STATUS_TEXT, RECORD_TYPE_TEXT, RECORD_CATEGORY_TEXT,
} from '../constants';

// 系统详情"运行处置记录"页签固定每页条数（1100px 系统详情弹窗内紧凑分页）
export const SYSTEM_RECORDS_PAGE_SIZE = 10;

class OperationRecordStore {
  // ========== 列表 ==========
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;
  // 列表加载失败标记：失败时保留旧数据但显式提示（不把旧结果冒充新查询结果），
  // 页面据此渲染"加载失败 + 重试"横幅；错误 toast 由 http 拦截器统一弹出
  @observable fetchError = false;

  // ========== 筛选条件 ==========
  // f_* 为"已执行"的查询条件：列表取数、导出参数与联动刷新一律以此为准
  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_system = undefined;
  @observable f_category = undefined;
  @observable f_record_type = undefined;
  @observable f_occurred_range = undefined;
  // 关键词输入草稿（输入中、未执行）：Input 绑定草稿，查询按钮/回车提交后
  // 才转正为 f_keyword，避免"输入未查询"的条件混入导出与联动刷新
  @observable input_keyword = '';

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
  // 详情加载失败标记：失败时页面渲染显式失败态与重试入口，不把列表行
  // 旧数据或空对象冒充完整详情；错误 toast 由 http 拦截器统一弹出
  @observable detailError = false;
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
  // 附件请求序号：快速切换记录时旧记录的迟到响应不覆盖新记录附件
  attachmentRequestSeq = 0;

  // ========== 动作执行中 ==========
  @observable isActionSubmitting = false;

  @action resetFilter = () => {
    this.input_keyword = '';
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_system = undefined;
    this.f_category = undefined;
    this.f_record_type = undefined;
    this.f_occurred_range = undefined;
    this.page = 1;
  };

  @action setKeywordInput = (value) => {
    this.input_keyword = value;
  };

  // 提交关键词草稿为已执行条件（查询按钮/回车共用）：任何提交都回到第 1 页
  commitKeyword = () => {
    this.f_keyword = this.input_keyword || undefined;
    this.page = 1;
    return this.fetchRecords();
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
        this.fetchError = false;
      }))
      .catch(action(() => {
        // 保留旧数据供参考，置失败标记由页面提示"加载失败可重试"
        this.fetchError = true;
      }))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  // 导出参数与列表"已执行"筛选完全一致（f_* 为唯一口径，关键词草稿不参与；
  // 后端导出接口接受同一组筛选，结束时间由后端按所选整分钟包含该分钟记录）
  getExportParams = () => {
    const params = {};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
    if (this.f_category) params.category = this.f_category;
    if (this.f_record_type) params.record_type = this.f_record_type;
    if (this.f_occurred_range && this.f_occurred_range.length === 2) {
      params.occurred_from = this.f_occurred_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.f_occurred_range[1].format('YYYY-MM-DD HH:mm');
    }
    return params;
  };

  // 当前是否带有任一筛选条件（筛选分层折叠计数用；导出口径见 exportScopeText）
  get hasActiveFilter() {
    return Boolean(
      this.f_keyword || this.f_status || this.f_system || this.f_category ||
      this.f_record_type ||
      (this.f_occurred_range && this.f_occurred_range.length === 2));
  }

  // 导出范围文案：与 getExportParams 同一已执行口径逐项列出，保证"导出范围"
  // 提示与真实导出内容一致（输入中的关键词草稿不出现在文案里）
  get exportScopeText() {
    const parts = [];
    if (this.f_keyword) parts.push(`关键词「${this.f_keyword}」`);
    if (this.f_system) {
      const option = this.systemOption(this.f_system);
      parts.push(`系统「${option ? option.name : this.f_system}」`);
    }
    if (this.f_status) {
      parts.push(`状态「${RECORD_STATUS_TEXT[this.f_status] || this.f_status}」`);
    }
    if (this.f_record_type) {
      parts.push(`类型「${RECORD_TYPE_TEXT[this.f_record_type] || this.f_record_type}」`);
    }
    if (this.f_category) {
      parts.push(`异常类别「${RECORD_CATEGORY_TEXT[this.f_category] || this.f_category}」`);
    }
    if (this.f_occurred_range && this.f_occurred_range.length === 2) {
      parts.push(`发生时间 ${this.f_occurred_range[0].format('YYYY-MM-DD HH:mm')}` +
        ` 至 ${this.f_occurred_range[1].format('YYYY-MM-DD HH:mm')}`);
    }
    if (!parts.length) return '导出范围：全部未撤销记录';
    return `导出范围：当前查询条件（${parts.join('、')}）命中的全部记录，分页不影响`;
  }

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
        // 新增/编辑可能改变行归属或字段值：系统页签在位时同步刷新
        this.refreshSystemRecordsIfActive();
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
    // 新记录重新加载：清失败标记（是否失败由本次请求结果决定）
    this.detailError = false;
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
          this.detailError = false;
        }
      }))
      .catch(action(() => {
        // 快速切换记录时旧请求的迟到失败不置失败标记（序号防护）
        if (requestSeq === this.detailRequestSeq) {
          this.detailError = true;
        }
      }))
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

  // 详情加载失败重试（详情失败态入口）：保持当前 detailId 与目标页签，
  // 重发详情/进展/附件三个请求（失败可能发生在任一请求），成功后由各自
  // 响应恢复正常显示
  retryDetailLoad = () => {
    this.fetchDetail();
    this.fetchProgressRecords();
    this.fetchAttachments();
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
    const requestSeq = ++this.attachmentRequestSeq;
    return http.get(`${API_PREFIX}/records/${this.detailId}/attachments/`)
      .then(action(res => {
        if (requestSeq === this.attachmentRequestSeq) {
          this.attachments = res.data || [];
        }
      }))
      .catch(action(() => {}));
  };

  // ========== 状态动作（成功后重新获取真实数据） ==========
  _refreshAfterAction = () => {
    this.fetchDetail();
    this.fetchProgressRecords();
    this.fetchRecords();
    // 完成跟进/认定故障/结案/撤销/追加进展等改变行状态或最新进展：
    // 系统页签在位时以同一组筛选联动刷新
    this.refreshSystemRecordsIfActive();
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

  // 认定设备故障：异常事件在原记录上认定（类型原地变更，不创建第二张单）
  identifyFault = (formData) => this._postAction('identify-fault', formData);

  // 确认恢复并结案：处置中 → 已关闭（设备故障，须同时具备 recover+close 权限）
  confirmRecoverAndClose = (formData) => this._postAction('recover', formData);

  // 撤销故障登记：处置中 → 已撤销（原因必填留痕）
  cancelRecord = (formData) => this._postAction('cancel', formData);

  // 原因分析专用保存（设备故障处置中）
  saveReasonAnalysis = (formData) => {
    this.isActionSubmitting = true;
    return http.put(`${API_PREFIX}/records/${this.detailId}/reason-analysis/`, formData)
      .then(action(() => this.fetchDetail()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // 删除记录（仅一般记录；成功后关闭详情并刷新列表真实数据）
  deleteRecord = () => {
    this.isActionSubmitting = true;
    return http.delete(`${API_PREFIX}/records/${this.detailId}/`)
      .then(action(() => {
        this.closeDetail();
        this.fetchRecords();
        // 系统页签在位时同步移除已删除行
        this.refreshSystemRecordsIfActive();
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  addProgressRecord = (formData) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/records/${this.detailId}/progress/`, formData)
      // 追加进展即"跟进"动作：异常事件保存首条进展后进入跟进中、已完成追加
      // 进展重新跟进；一般记录仅补充留痕不改状态，成功后全量刷新详情/进展/
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
      // 更正可能修改处理时间：最新进展时间/持续时间随详情与列表重算，
      // 与追加进展同样全量刷新真实数据
      .then(action(() => this._refreshAfterAction()))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // ========== 系统详情"运行处置记录"页签 ==========
  @observable systemRecords = [];
  @observable systemRecordsTotal = 0;
  @observable systemLatestOccurredAt = null;
  @observable isSystemRecordsFetching = false;
  // 页签加载失败标记：失败时保留旧数据并显式提示重试
  @observable systemRecordsError = false;
  // 页签当前查看的系统 ID：页签挂载随首次取数设置、卸载清空；
  // 详情动作后的联动刷新（refreshSystemRecordsIfActive）以此判断页签在位
  @observable systemRecordsSystemId = null;
  // 页签请求序号：换系统/快速翻页时只接受最后一次响应，避免旧结果回写
  systemRecordsRequestSeq = 0;
  // 页签筛选（语义与主列表一致；系统由档案固定，不设系统条件）。
  // 收进 store 使查询/重置/翻页/失败重试与详情动作后的联动刷新
  // 始终使用同一组条件
  @observable sf_keyword = undefined;
  // 页签关键词输入草稿（输入中、未执行）：语义与主列表 input_keyword 一致，
  // 查询按钮/回车提交后才转正为 sf_keyword
  @observable sf_input_keyword = '';
  @observable sf_status = undefined;
  @observable sf_category = undefined;
  @observable sf_record_type = undefined;
  @observable sf_occurred_range = undefined;
  @observable systemRecordsPage = 1;

  resetSystemFilter = action(() => {
    this.sf_input_keyword = '';
    this.sf_keyword = undefined;
    this.sf_status = undefined;
    this.sf_category = undefined;
    this.sf_record_type = undefined;
    this.sf_occurred_range = undefined;
    this.systemRecordsPage = 1;
  });

  // 页签是否带有任一筛选条件（空态区分"系统无记录"与"筛选后无匹配"）
  get systemHasActiveFilter() {
    return Boolean(
      this.sf_keyword || this.sf_status || this.sf_category ||
      this.sf_record_type ||
      (this.sf_occurred_range && this.sf_occurred_range.length === 2));
  }

  // 页签系统上下文：systemId 变化即重置筛选/页码与关键词草稿（换系统不带入
  // 上一系统的条件）。fetchSystemRecords 与 querySystemRecords 共用同一判定
  _ensureSystemContext = (systemId) => {
    if (systemId !== undefined && systemId !== null
        && systemId !== this.systemRecordsSystemId) {
      this.resetSystemFilter();
      this.systemRecordsSystemId = systemId;
    }
  };

  @action setSystemKeywordInput = (value) => {
    this.sf_input_keyword = value;
  };

  // 页签查询提交（查询按钮/回车共用）：先走换系统重置判定，再提交关键词
  // 草稿并取数，保证取数参数与提交后的已执行条件一致；任何提交都回到第 1 页
  querySystemRecords = (systemId) => {
    this._ensureSystemContext(systemId);
    this.sf_keyword = this.sf_input_keyword || undefined;
    return this.fetchSystemRecords(systemId, 1);
  };

  // systemId 变化即重置筛选与页码（换系统不带入上一系统的条件）；
  // page 传入时切换页码。不传 systemId 时沿用当前在位系统（重试/联动刷新）
  fetchSystemRecords = (systemId, page) => {
    this._ensureSystemContext(systemId);
    if (page !== undefined) this.systemRecordsPage = page;
    const targetSystemId = this.systemRecordsSystemId;
    if (!targetSystemId) return Promise.resolve();
    const params = {page: this.systemRecordsPage, page_size: SYSTEM_RECORDS_PAGE_SIZE};
    if (this.sf_keyword) params.keyword = this.sf_keyword;
    if (this.sf_status) params.status = this.sf_status;
    if (this.sf_category) params.category = this.sf_category;
    if (this.sf_record_type) params.record_type = this.sf_record_type;
    if (this.sf_occurred_range && this.sf_occurred_range.length === 2) {
      params.occurred_from = this.sf_occurred_range[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = this.sf_occurred_range[1].format('YYYY-MM-DD HH:mm');
    }
    const requestSeq = ++this.systemRecordsRequestSeq;
    this.isSystemRecordsFetching = true;
    return http.get(`${API_PREFIX}/systems/${targetSystemId}/records/`, {params})
      .then(action(res => {
        if (requestSeq !== this.systemRecordsRequestSeq) return;
        this.systemRecords = res.data || [];
        this.systemRecordsTotal = res.total || 0;
        this.systemLatestOccurredAt = res.latest_occurred_at;
        this.systemRecordsError = false;
      }))
      .catch(action(() => {
        if (requestSeq !== this.systemRecordsRequestSeq) return;
        this.systemRecordsError = true;
      }))
      .finally(action(() => {
        if (requestSeq === this.systemRecordsRequestSeq) {
          this.isSystemRecordsFetching = false;
        }
      }));
  };

  // 详情内新增/编辑/删除/状态动作成功后联动刷新系统页签（页签在位时以
  // 同一组筛选与页码重新取数，不显示过期行；换系统场景行归属已变化同样
  // 由服务端筛选结果修正）
  refreshSystemRecordsIfActive = () => {
    if (this.systemRecordsSystemId) {
      return this.fetchSystemRecords();
    }
    return Promise.resolve();
  };

  // 页签卸载（关闭系统详情/离开系统档案页）时清空数据与在位标记
  clearSystemRecords = action(() => {
    this.systemRecordsSystemId = null;
    this.systemRecords = [];
    this.systemRecordsTotal = 0;
    this.systemLatestOccurredAt = null;
    this.systemRecordsError = false;
  });

  // ========== 待办列表 ==========
  // 跟进中的异常事件 + 处置中的设备故障（真正需要持续处理的两类记录），
  // 后端分页返回；counts 为全量分组计数（不随类型筛选变化）
  @observable todoRecords = [];
  @observable todoTotal = 0;
  @observable todoPage = 1;
  @observable todoPageSize = 20;
  @observable todoCounts = null;
  @observable f_todo_record_type = undefined;
  @observable isTodoFetching = false;
  @observable todoError = false;
  todoRequestSeq = 0;

  fetchTodoRecords = () => {
    const requestSeq = ++this.todoRequestSeq;
    this.isTodoFetching = true;
    const params = {page: this.todoPage, page_size: this.todoPageSize};
    if (this.f_todo_record_type) params.record_type = this.f_todo_record_type;
    return http.get(`${API_PREFIX}/records/todo/`, {params})
      .then(action(res => {
        if (requestSeq === this.todoRequestSeq) {
          this.todoRecords = res.data || [];
          this.todoTotal = res.total || 0;
          this.todoCounts = res.counts || null;
          this.todoError = false;
        }
      }))
      .catch(action(() => {
        if (requestSeq === this.todoRequestSeq) {
          this.todoError = true;
        }
      }))
      .finally(action(() => {
        if (requestSeq === this.todoRequestSeq) {
          this.isTodoFetching = false;
        }
      }));
  };

  setTodoRecordType = action((value) => {
    this.f_todo_record_type = value;
    this.todoPage = 1;
    return this.fetchTodoRecords();
  });

  // ========== 统计 ==========
  @observable statistics = null;
  @observable isStatisticsFetching = false;
  @observable statsError = false;
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
          this.statsError = false;
        }
      }))
      .catch(action(() => {
        if (requestSeq === this.statisticsRequestSeq) {
          this.statsError = true;
        }
      }))
      .finally(action(() => {
        if (requestSeq === this.statisticsRequestSeq) {
          this.isStatisticsFetching = false;
        }
      }));
  };
}

export default new OperationRecordStore();
