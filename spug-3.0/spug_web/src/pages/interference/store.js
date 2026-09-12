import { observable, action } from 'mobx';
import { http, syncAttachmentCount } from 'libs';

class InterferenceStore {
  @observable events = [];
  @observable event = {};
  @observable eventsLoading = false;
  @observable investigations = [];
  @observable investigation = {};
  @observable investigationsLoading = false;
  @observable page = 1;
  @observable pageSize = 20;
  @observable total = 0;
  @observable eventFilters = {};
  @observable investigationName = '';
  @observable investigationStatus;
  @observable eventModalVisible = false;
  @observable investigationModalVisible = false;

  @action.bound
  fetchEvents(params = {}) {
    this.eventsLoading = true;
    const query = {
      page: this.page,
      page_size: this.pageSize,
      ...this.eventFilters,
      ...params,
    };
    return http.get('/api/interference/events/', {params: query})
      .then(({records, total, page, page_size}) => {
        this.events = records || [];
        this.total = total || 0;
        this.page = page || this.page;
        this.pageSize = page_size || this.pageSize;
        return this.events;
      })
      .finally(() => { this.eventsLoading = false; });
  }

  @action.bound
  fetchEvent(id) {
    return http.get(`/api/interference/events/${id}/`).then(data => {
      this.event = data || {};
      return this.event;
    });
  }

  @action.bound
  fetchInvestigations(params = {}) {
    this.investigationsLoading = true;
    return http.get('/api/interference/investigations/', {params: {
      page: this.page,
      page_size: this.pageSize,
      ...params,
    }}).then(({records, total, page, page_size}) => {
      this.investigations = records || [];
      this.total = total || 0;
      this.page = page || this.page;
      this.pageSize = page_size || this.pageSize;
      return this.investigations;
    }).finally(() => { this.investigationsLoading = false; });
  }

  @action.bound
  fetchInvestigation(id) {
    return http.get(`/api/interference/investigations/${id}/`).then(data => {
      this.investigation = data || {};
      return this.investigation;
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
