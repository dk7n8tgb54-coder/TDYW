/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, action, computed } from 'mobx';
import { http } from 'libs';

class Store {
  @observable templates = [];
  @observable isFetching = false;
  @observable templateRecord = {};
  @observable templateFormVisible = false;
  @observable f_project = '';
  @observable checkRecords = [];
  @observable statistics = {};

  @observable projects = [];

  @computed get filteredTemplates() {
    console.log('[CheckSheet Store] filteredTemplates called, f_project:', this.f_project, 'templates:', this.templates);
    if (!this.f_project) return this.templates;
    return this.templates.filter(item => item.project.includes(this.f_project));
  }

  @action fetchTemplates = () => {
    this.isFetching = true;
    return http.get('/api/checksheet/template/')
      .then(res => {
        // P3-2 修复：移除调试日志
        this.templates = res.templates || [];
        this.projects = [...new Set(this.templates.map(t => t.project).filter(Boolean))];
      })
      .finally(() => this.isFetching = false);
  };

  @action showTemplateForm = (record) => {
    this.templateRecord = record || {};
    this.templateFormVisible = true;
  };

  @action saveTemplate = (data) => {
    if (this.templateRecord.id) {
      return http.put(`/api/checksheet/template/${this.templateRecord.id}/`, data);
    } else {
      return http.post('/api/checksheet/template/', data);
    }
  };

  @action deleteTemplate = (id) => {
    return http.delete(`/api/checksheet/template/${id}/`);
  };

  @action fetchCheckRecords = (year, month, project, day) => {
    const dayParam = day ? `&day=${day}` : '';
    return http.get(`/api/checksheet/record/?year=${year}&month=${month}&project=${project}${dayParam}`)
      .then(res => res);
  };

  @action saveCheckRecords = (data) => {
    return http.post('/api/checksheet/record/', data);
  };

  @action exportPDF = (year, month, project) => {
    // 注意：PDF 导出已迁移至 useDataViewExport hook（见 hooks/useDataViewExport.js）
    // 此方法保留仅用于兼容，不再有实际作用
    console.warn('[CheckSheet Store] exportPDF is deprecated, use useDataViewExport instead');
    return Promise.resolve();
  };
}

export default new Store();
