/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

class Store {
  // === 列表数据 ===
  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // === 筛选选项（从后端获取，预设系统+历史系统合并）===
  @observable filterOptions = { systems: [], upgradeTypes: [], statuses: [], phases: [], milestones: [], standard_flow: [] };

  // === 筛选条件 ===
  @observable f_system;
  @observable f_status;
  @observable f_start_date;
  @observable f_end_date;
  @observable f_upgrade_type;
  @observable f_export_date_range;

  // === 表单 ===
  @observable record = {};
  @observable formVisible = false;
  @observable createVisible = false;
  @observable presetPlanId = null;

  // === 视图模式 ===
  @observable viewMode = 'list'; // 'list' | 'calendar'

  // === 升级方案（合并原模板+步骤清单）===
  @observable plans = [];

  // === 升级系统候选项（仅 active 字典项，用于新建/编辑表单的 SystemSelect）===
  // 注意：与 filterOptions.systems 不同——后者含历史兜底，用于列表筛选；
  //       本字段仅含字典表 active 项，停用后立即从下拉消失。
  @observable systems = [];

  // === 工作台相关状态 ===
  @observable recordSteps = [];
  @observable recordStepStats = {};
  @observable statusLogs = [];
  @observable actionOptions = [];
  @observable attachmentCount = 0;

  // === 工作台数据加载 ===
  fetchRecord = (id) => {
    return http.get(`/api/upgrade/records/${id}/`)
      .then(data => {
        this.record = data || {};
        return data;
      })
      .catch((error) => {
        console.error('[Upgrade Store] Record error:', error);
        throw error;
      });
  };

  fetchAttachmentCount = (id) => {
    if (!id) return Promise.resolve();
    return http.get(`/api/upgrade/records/${id}/attachments/`)
      .then(data => {
        this.attachmentCount = (data || []).length;
      })
      .catch(() => {
        this.attachmentCount = 0;
      });
  };

  setAttachmentCount = (count) => {
    this.attachmentCount = count;
  };

  fetchRecordSteps = (id) => {
    if (!id) return Promise.resolve();
    return http.get(`/api/upgrade/records/${id}/steps/`)
      .then(res => {
        this.recordSteps = res.steps || [];
        this.recordStepStats = res.stats || { total: 0, completed: 0, skipped: 0, pending: 0, progress: 0 };
      })
      .catch(() => {
        this.recordSteps = [];
        this.recordStepStats = { total: 0, completed: 0, skipped: 0, pending: 0, progress: 0 };
      });
  };

  fetchStatusLogs = (id) => {
    if (!id) return Promise.resolve();
    return http.get(`/api/upgrade/records/${id}/status-logs/`)
      .then(data => {
        this.statusLogs = data || [];
      })
      .catch(() => {
        this.statusLogs = [];
      });
  };

  fetchActionOptions = (id) => {
    if (!id) return Promise.resolve();
    return http.get(`/api/upgrade/records/${id || 0}/status-logs/?action=options`)
      .then(data => {
        this.actionOptions = data || [];
      })
      .catch(() => {
        this.actionOptions = [];
      });
  };

  // === 列表接口（分页）===
  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.page,
      page_size: this.pageSize,
    };
    if (this.f_system) params.system = this.f_system;
    if (this.f_status) params.status = this.f_status;
    if (this.f_upgrade_type) params.upgrade_type = this.f_upgrade_type;
    if (this.f_start_date) params.start_date = this.f_start_date;
    if (this.f_end_date) params.end_date = this.f_end_date;

    http.get('/api/upgrade/records/', {params})
      .then((data) => {
        this.records = data.records || [];
        this.total = data.total || 0;
      })
      .catch((error) => {
        console.error('[Upgrade Store] Error:', error);
      })
      .finally(() => this.isFetching = false)
  };

  // === 筛选选项接口 ===
  fetchFilterOptions = () => {
    return http.get('/api/upgrade/filter-options/')
      .then((data) => {
        this.filterOptions = {
          systems: data.systems || [],
          upgradeTypes: data.upgrade_types || [],
          statuses: data.statuses || [],
          phases: data.phases || [],
          milestones: data.milestones || [],
          standard_flow: data.standard_flow || [],
        };
      })
      .catch((error) => {
        console.error('[Upgrade Store] Filter options error:', error);
      });
  };

  // === 表单操作 ===
  showForm = (info = {}, isViewMode = false) => {
    this.formVisible = true;
    this.record = {...info, isViewMode};
  };

  showDetail = (info) => {
    this.formVisible = true;
    this.record = {...info, isViewMode: true};
  };

  // === 新建升级弹窗 ===
  showCreateForm = (planId = null) => {
    this.presetPlanId = planId;
    this.createVisible = true;
  };

  hideCreateForm = () => {
    this.createVisible = false;
    this.presetPlanId = null;
  };

  // === 统计接口 ===
  fetchStatistics = (filters = {}) => {
    const params = {};
    if (filters.system) params.system = filters.system;
    if (filters.start_date && filters.end_date) {
      params.start_date = filters.start_date;
      params.end_date = filters.end_date;
    }
    return http.get('/api/upgrade/statistics/', {params});
  };

  // === 升级方案接口（合并原模板+步骤清单）===
  fetchPlans = () => {
    return http.get('/api/upgrade/plans/')
      .then((data) => {
        this.plans = data || [];
      })
      .catch((error) => {
        console.error('[Upgrade Store] Plans error:', error);
      });
  };

  // === 升级系统候选项接口（仅 active 字典项）===
  fetchSystems = () => {
    return http.get('/api/upgrade/systems/')
      .then((data) => {
        this.systems = data || [];
      })
      .catch((error) => {
        console.error('[Upgrade Store] Systems error:', error);
      });
  };

  // 乐观移除：立即从本地 systems 过滤掉指定 name，UI 即时更新
  removeSystem = (name) => {
    this.systems = this.systems.filter(s => s.name !== name);
  };

  // 乐观新增：立即把新项追加到本地 systems
  addSystem = (system) => {
    if (system && !this.systems.some(s => s.name === system.name)) {
      this.systems = [...this.systems, system];
    }
  };

  fetchPlanDetail = (id) => {
    return http.get(`/api/upgrade/plans/${id}/`)
      .catch((error) => {
        console.error('[Upgrade Store] Plan detail error:', error);
        return null;
      });
  };

  createPlan = (data) => {
    return http.post('/api/upgrade/plans/create/', data);
  };

  updatePlan = (id, data) => {
    return http.put(`/api/upgrade/plans/${id}/update/`, data);
  };

  deletePlan = (id) => {
    return http.delete(`/api/upgrade/plans/${id}/delete/`);
  };

  // 应用方案预设步骤到升级记录（实例化为记录步骤）
  applyPlan = (planId, upgradeId, replace = false) => {
    return http.post(`/api/upgrade/plans/${planId}/apply/`, { upgrade_id: upgradeId, replace });
  };

  getExportParams = () => {
    const params = {};
    if (this.f_system) params.system = this.f_system;
    if (this.f_status) params.status = this.f_status;
    if (this.f_upgrade_type) params.upgrade_type = this.f_upgrade_type;
    // 日期范围：优先用导出专用范围，否则用搜索日期范围
    if (this.f_export_date_range && this.f_export_date_range.length === 2) {
      params.start_date = this.f_export_date_range[0].format('YYYY-MM-DD');
      params.end_date = this.f_export_date_range[1].format('YYYY-MM-DD');
    } else if (this.f_start_date && this.f_end_date) {
      params.start_date = this.f_start_date;
      params.end_date = this.f_end_date;
    }
    return params;
  };
}

export default new Store()
