import { observable, action } from 'mobx';
import { http, syncAttachmentCount } from 'libs';

class InterferenceStore {
  @observable events = [];
  @observable event = {};
  @observable eventsLoading = false;
  @observable investigations = [];
  @observable investigation = {};
  @observable investigationsLoading = false;
  // 事件列表分页（page/pageSize/total 只归事件列表所有）
  @observable page = 1;
  @observable pageSize = 20;
  @observable total = 0;
  // 调查列表独立分页（2026-10-25）：此前与事件列表共用 page/pageSize/total，
  // 事件页「加入已有调查」弹窗加载调查选项（page=1&page_size=100）会把
  // 事件表格的分页状态改成 1/100，调查列表翻页也会窜进事件列表请求参数。
  @observable investigationPage = 1;
  @observable investigationPageSize = 20;
  @observable investigationTotal = 0;
  // 请求代次守卫：仅最新一次请求允许写入列表状态，防止乱序返回时旧
  // 响应覆盖新结果（仓库既有模式，见 radioLicense/store.js _fetchSeq、
  // equipmentLifecycle/systemConfig/store.js detailRequestSeq）。
  _eventsRequestSeq = 0;
  _investigationsRequestSeq = 0;
  @observable eventFilters = {};
  @observable investigationName = '';
  @observable investigationStatus;
  @observable eventModalVisible = false;
  @observable investigationModalVisible = false;
  // 三个分类下拉的选项（全平台共用字典，后端接口下发）
  @observable categoryOptions = {
    interference_kind_code: [],
    affected_system_code: [],
    source_type_code: [],
  };

  @action.bound
  fetchEvents(params = {}) {
    const seq = ++this._eventsRequestSeq;
    this.eventsLoading = true;
    const query = {
      page: this.page,
      page_size: this.pageSize,
      ...this.eventFilters,
      ...params,
    };
    return http.get('/api/interference/events/', {params: query})
      .then(({records, total, page, page_size}) => {
        // 过期响应（其后已发起更新请求）不得写入列表状态
        if (seq !== this._eventsRequestSeq) return this.events;
        this.events = records || [];
        this.total = total || 0;
        this.page = page || this.page;
        this.pageSize = page_size || this.pageSize;
        return this.events;
      })
      .finally(() => {
        // 仅最新请求有权复位 loading，避免旧请求提前关闭新请求的加载态
        if (seq === this._eventsRequestSeq) this.eventsLoading = false;
      });
  }

  @action.bound
  fetchEvent(id) {
    // 只返回数据、不写回 store.event（2026-10-26 用户实测缺陷修复）：EventForm
    // 的详情 effect 依赖 [visible, info, infoId, form]，info 即 store.event 引用——
    // 旧实现每次响应把新对象写回 store.event，info 引用随之变化，effect 先执行
    // cleanup（form.resetFields() 清空表单）再重跑并再次 fetch，形成无限循环
    // （表单全空、点击无响应、接口重复请求），且 showEvent 注入的 isViewMode
    // 会被首个响应覆写丢失（查看态静默翻成可编辑）。store.event 仅由
    // showEvent/closeEvent 写入，本方法的全量消费者只读取返回值。
    return http.get(`/api/interference/events/${id}/`).then(data => data || {});
  }

  @action.bound
  fetchInvestigations(params = {}) {
    const seq = ++this._investigationsRequestSeq;
    this.investigationsLoading = true;
    // 显式携带分页参数的调用（事件页「加入已有调查」弹窗按
    // page=1&page_size=100 拉选项）是选择器查询，不回写调查列表的
    // 分页状态，避免 100/页 的选择器口径残留到列表页。
    const explicitPagination = 'page' in params || 'page_size' in params;
    return http.get('/api/interference/investigations/', {params: {
      page: this.investigationPage,
      page_size: this.investigationPageSize,
      ...params,
    }}).then(({records, total, page, page_size}) => {
      if (seq !== this._investigationsRequestSeq) return this.investigations;
      this.investigations = records || [];
      if (!explicitPagination) {
        this.investigationTotal = total || 0;
        this.investigationPage = page || this.investigationPage;
        this.investigationPageSize = page_size || this.investigationPageSize;
      }
      return this.investigations;
    }).finally(() => {
      if (seq === this._investigationsRequestSeq) this.investigationsLoading = false;
    });
  }

  @action.bound
  fetchInvestigation(id) {
    // 只返回数据、不写回 store.investigation（2026-10-26 用户实测缺陷修复，
    // 与 fetchEvent 同型）：InvestigationForm 的详情 effect 依赖 [visible, info,
    // infoId, form]，info 即 store.investigation 引用——旧实现每次响应把新对象
    // 写回 store.investigation，effect 先 resetFields 清空表单再重跑并再次
    // fetch，无限循环；showInvestigation 注入的 isViewMode 也被覆写丢失。
    // store.investigation 仅由 showInvestigation/closeInvestigation 写入，
    // 本方法的全量消费者（表单 effect、addMeasurement 刷新）只读取返回值。
    return http.get(`/api/interference/investigations/${id}/`).then(data => data || {});
  }

  @action.bound
  fetchCategories() {
    return http.get('/api/interference/categories/').then(data => {
      const options = {
        interference_kind_code: [],
        affected_system_code: [],
        source_type_code: [],
      };
      for (const item of (data && data.records) || []) {
        const key = `${item.group}_code`;
        if (options[key]) options[key].push({value: item.code, label: item.name});
      }
      this.categoryOptions = options;
      return options;
    });
  }

  @action.bound
  showEvent(event = {}) {
    this.event = {...event};
    this.eventModalVisible = true;
  }

  @action.bound
  closeEvent() {
    this.eventModalVisible = false;
    this.event = {};
  }

  @action.bound
  showInvestigation(investigation = {}) {
    this.investigation = {...investigation};
    this.investigationModalVisible = true;
  }

  @action.bound
  closeInvestigation() {
    this.investigationModalVisible = false;
    this.investigation = {};
  }

  updateAttachmentCount = (id, count) => syncAttachmentCount(this, id, count);
}

export default new InterferenceStore();
