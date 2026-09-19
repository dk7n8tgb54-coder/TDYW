/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——工单管理状态管理（MobX, legacy decorators）。
 * 业务关联一律使用系统 ID / 用户 ID；成功提示等待后端真实成功
 * （http.js 拦截器统一提示 error，业务代码不重复提示）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from '../constants';

function uuid() {
  return 'wo-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
}

class WorkOrderStore {
  // ========== 工单列表 ==========
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // ========== 筛选条件 ==========
  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_work_type = undefined;
  @observable f_priority = undefined;
  @observable f_system = undefined;
  @observable f_source_type = undefined;

  // ========== 表单 ==========
  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;
  // 幂等令牌：每次打开表单生成，同一表单生命周期内重复提交携带相同令牌
  @observable formToken = '';

  // ========== 候选项 ==========
  @observable systems = [];
  @observable users = [];

  // ========== 详情抽屉（列表页入口；组件内嵌场景见 WorkOrderDetail props 用法） ==========
  @observable detailVisible = false;
  @observable detailId = null;
  @observable detail = {};
  @observable isDetailFetching = false;
  @observable handlingRecords = [];
  @observable isHandlingFetching = false;
  @observable isActionSubmitting = false;

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_work_type = undefined;
    this.f_priority = undefined;
    this.f_system = undefined;
    this.f_source_type = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_work_type) params.work_type = this.f_work_type;
    if (this.f_priority) params.priority = this.f_priority;
    if (this.f_system) params.system = this.f_system;
    if (this.f_source_type) params.source_type = this.f_source_type;
    return http.get(`${API_PREFIX}/work-orders/`, {params})
      .then(action(res => {
        this.records = res.data;
        this.total = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  fetchCandidates = () => {
    return Promise.all([
      http.get(`${API_PREFIX}/work-orders/candidate-systems/`),
      http.get(`${API_PREFIX}/work-orders/candidate-users/`),
    ]).then(action(([sysRes, userRes]) => {
      this.systems = sysRes.data || [];
      this.users = userRes.data || [];
    })).catch(action(() => {}));
  };

  systemOption = (id) => this.systems.find(s => s.id === id);

  showForm = action((record = {}) => {
    this.record = record;
    this.formToken = uuid();
    this.formVisible = true;
    this.fetchCandidates();
  });

  buildFormPayload = (values) => {
    // 所有业务关联一律提交 ID（系统 ID、用户 ID），不提交名称
    const payload = {
      title: values.title,
      work_type: values.work_type,
      priority: values.priority || 'normal',
      target_system: values.target_system,
      affected_system_ids: values.affected_system_ids || [],
      work_location: values.work_location || '',
      work_object_desc: values.work_object_desc || '',
      work_component: values.work_component || undefined,
      work_requirement: values.work_requirement || '',
      work_steps: values.work_steps || '',
      material_note: values.material_note || '',
      client_token: this.formToken,
    };
    if (values.planned_range && values.planned_range.length === 2) {
      payload.planned_start = values.planned_range[0].format('YYYY-MM-DD HH:mm');
      payload.planned_end = values.planned_range[1].format('YYYY-MM-DD HH:mm');
    }
    return payload;
  };

  submitForm = (values) => {
    this.isSubmitting = true;
    const isEdit = !!this.record.id;
    const payload = this.buildFormPayload(values);
    const request = isEdit
      ? http.put(`${API_PREFIX}/work-orders/${this.record.id}/`, payload)
      : http.post(`${API_PREFIX}/work-orders/`, payload);
    return request
      .then(action(() => {
        this.formVisible = false;
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  // ========== 详情 ==========
  showDetail = action((recordOrId) => {
    this.detailId = typeof recordOrId === 'object' ? recordOrId.id : recordOrId;
    this.detail = typeof recordOrId === 'object' ? recordOrId : {};
    this.detailVisible = true;
    this.handlingRecords = [];
    this.fetchDetail();
    this.fetchHandlingRecords();
  });

  closeDetail = action(() => {
    this.detailVisible = false;
    this.detailId = null;
  });

  fetchDetail = (id = this.detailId) => {
    if (!id) return Promise.resolve();
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX}/work-orders/${id}/`)
      .then(action(res => {
        this.detail = res;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isDetailFetching = false;
      }));
  };

  fetchHandlingRecords = (id = this.detailId) => {
    if (!id) return Promise.resolve();
    this.isHandlingFetching = true;
    return http.get(`${API_PREFIX}/work-orders/${id}/handling-records/`)
      .then(action(res => {
        this.handlingRecords = res.data;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isHandlingFetching = false;
      }));
  };

  // ========== 状态动作（成功后重新获取后端真实数据） ==========
  runAction = (actionName, extra = {}, id = this.detailId) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/work-orders/${id}/${actionName}/`, extra)
      .then(action(res => {
        this.detail = res;
        this.fetchHandlingRecords(id);
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  dispatch = (formData, id = this.detailId) => this.runAction('dispatch', formData, id);
  accept = (id = this.detailId) => this.runAction('accept', {}, id);
  start = (id = this.detailId) => this.runAction('start', {}, id);
  submitReview = (formData, id = this.detailId) => this.runAction('submit-review', formData, id);
  reviewPass = (formData, id = this.detailId) => this.runAction('review-pass', formData, id);
  reviewReturn = (formData, id = this.detailId) => this.runAction('review-return', formData, id);
  close = (id = this.detailId) => this.runAction('close', {}, id);
  cancel = (formData, id = this.detailId) => this.runAction('cancel', formData, id);

  addHandlingRecord = (formData, id = this.detailId) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/work-orders/${id}/handling-records/`, formData)
      .then(action(() => {
        this.fetchHandlingRecords(id);
        return this.fetchDetail(id);
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  correctHandlingRecord = (recordId, formData, id = this.detailId) => {
    this.isActionSubmitting = true;
    return http.put(
      `${API_PREFIX}/work-orders/${id}/handling-records/${recordId}/`, formData)
      .then(action(() => {
        this.fetchHandlingRecords(id);
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  // ========== 故障生成维修工单 ==========
  @observable convertVisible = false;
  @observable convertSource = {}; // 来源故障或台账明细上下文

  showConvertFromFault = action((fault) => {
    this.convertSource = fault;
    this.formToken = uuid();
    this.convertVisible = true;
    this.fetchCandidates();
  });

  submitConvertFromFault = (values) => {
    this.isSubmitting = true;
    const payload = this.buildFormPayload(values);
    return http.post(
      `${API_PREFIX}/faults/${this.convertSource.id}/create-work-order/`, payload)
      .then(action(() => {
        this.convertVisible = false;
        this.fetchRecords();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  // ========== 系统详情工单页签 ==========
  @observable systemOrders = [];
  @observable isSystemOrdersFetching = false;
  @observable systemOrderRole = 'all';

  fetchSystemOrders = (systemId, role = 'all') => {
    this.systemOrderRole = role;
    this.isSystemOrdersFetching = true;
    return http.get(`${API_PREFIX}/systems/${systemId}/work-orders/`, {params: {role}})
      .then(action(res => {
        this.systemOrders = res.data || [];
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isSystemOrdersFetching = false;
      }));
  };
}

export default new WorkOrderStore();
export {uuid};
