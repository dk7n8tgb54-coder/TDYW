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
  @observable filterOptions = { systems: [], upgradeTypes: [], statuses: [] };

  // === 筛选条件 ===
  @observable f_system;
  @observable f_status;
  @observable f_start_date;
  @observable f_end_date;
  @observable f_upgrade_type;

  // === 表单 ===
  @observable record = {};
  @observable formVisible = false;

  // === 视图模式 ===
  @observable viewMode = 'list'; // 'list' | 'calendar'

  // === 升级模板 ===
  @observable templates = [];
  @observable templateFormVisible = false;
  @observable editingTemplate = null;

  // === 步骤清单 ===
  @observable checklists = [];

  // === 自动生成的升级单号 ===
  @observable nextUpgradeNo = '';

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
        };
      })
      .catch((error) => {
        console.error('[Upgrade Store] Filter options error:', error);
      });
  };

  // === 获取自动生成的升级单号 ===
  fetchNextUpgradeNo = () => {
    return http.get('/api/upgrade/next-no/')
      .then((data) => {
        this.nextUpgradeNo = data.upgrade_no || '';
        return data.upgrade_no;
      })
      .catch((error) => {
        console.error('[Upgrade Store] Next no error:', error);
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

  // === 升级模板接口 ===
  fetchTemplates = () => {
    return http.get('/api/upgrade/templates/')
      .then((data) => {
        this.templates = data || [];
      })
      .catch((error) => {
        console.error('[Upgrade Store] Templates error:', error);
      });
  };

  createTemplate = (data) => {
    return http.post('/api/upgrade/templates/create/', data);
  };

  updateTemplate = (id, data) => {
    return http.put(`/api/upgrade/templates/${id}/update/`, data);
  };

  deleteTemplate = (id) => {
    return http.delete(`/api/upgrade/templates/${id}/delete/`);
  };

  // === 步骤清单接口 ===
  fetchChecklists = () => {
    return http.get('/api/upgrade/checklists/')
      .then((data) => {
        this.checklists = data || [];
      })
      .catch((error) => {
        console.error('[Upgrade Store] Checklists error:', error);
      });
  };

  fetchChecklistDetail = (id) => {
    return http.get(`/api/upgrade/checklists/${id}/`)
      .catch((error) => {
        console.error('[Upgrade Store] Checklist detail error:', error);
        return null;
      });
  };

  createChecklist = (data) => {
    return http.post('/api/upgrade/checklists/create/', data);
  };

  updateChecklist = (id, data) => {
    return http.put(`/api/upgrade/checklists/${id}/update/`, data);
  };

  deleteChecklist = (id) => {
    return http.delete(`/api/upgrade/checklists/${id}/delete/`);
  };
}

export default new Store()
