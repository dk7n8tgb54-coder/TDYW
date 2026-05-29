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
        console.log('[CheckSheet Store] fetchTemplates response:', res);
        console.log('[CheckSheet Store] response type:', typeof res);
        console.log('[CheckSheet Store] response.keys:', Object.keys(res || {}));
        console.log('[CheckSheet Store] res.templates:', res.templates);
        this.templates = res.templates || [];
        this.projects = [...new Set(this.templates.map(t => t.project).filter(Boolean))];
        console.log('[CheckSheet Store] templates count:', this.templates.length);
        console.log('[CheckSheet Store] templates:', this.templates);
        console.log('[CheckSheet Store] projects:', this.projects);
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
    // 使用前端导出 PDF，不再调用后端
    return Promise.resolve();
  };
}

export default new Store();
