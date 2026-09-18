/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统类型管理与类型字段模板。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from '../constants';

class TypeStore {
  @observable types = [];
  @observable isFetching = false;

  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;

  @observable drawerVisible = false;
  @observable currentType = {};
  @observable fields = [];
  @observable isFieldsFetching = false;

  @observable fieldFormVisible = false;
  @observable fieldRecord = null;
  @observable isFieldSubmitting = false;

  fetchTypes = () => {
    this.isFetching = true;
    return http.get(`${API_PREFIX}/system-types/`)
      .then(action(res => {
        this.types = res.data;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  showForm = action((record = {}) => {
    this.record = record;
    this.formVisible = true;
  });

  submitForm = (formData) => {
    this.isSubmitting = true;
    const request = this.record.id
      ? http.put(`${API_PREFIX}/system-types/${this.record.id}/`, formData)
      : http.post(`${API_PREFIX}/system-types/`, formData);
    return request
      .then(action(() => {
        this.formVisible = false;
        this.fetchTypes();
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  deleteType = (record) => {
    return http.delete(`${API_PREFIX}/system-types/${record.id}/`)
      .then(action(() => {
        this.fetchTypes();
      }));
  };

  showFields = action((record) => {
    this.currentType = record;
    this.drawerVisible = true;
    this.fetchFields(record.id);
  });

  fetchFields = (typeId) => {
    this.isFieldsFetching = true;
    return http.get(`${API_PREFIX}/system-types/${typeId}/fields/`)
      .then(action(res => {
        this.fields = res.data;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFieldsFetching = false;
      }));
  };

  showFieldForm = action((record = null) => {
    this.fieldRecord = record;
    this.fieldFormVisible = true;
  });

  submitField = (formData) => {
    this.isFieldSubmitting = true;
    const isEdit = !!(this.fieldRecord && this.fieldRecord.id);
    const typeId = this.currentType.id;
    const request = isEdit
      ? http.put(`${API_PREFIX}/system-types/${typeId}/fields/${this.fieldRecord.id}/`, formData)
      : http.post(`${API_PREFIX}/system-types/${typeId}/fields/`, formData);
    return request
      .then(action(() => {
        this.fieldFormVisible = false;
        this.fetchFields(typeId);
        this.fetchTypes();
      }))
      .finally(action(() => {
        this.isFieldSubmitting = false;
      }));
  };

  deleteField = (record) => {
    return http.delete(
      `${API_PREFIX}/system-types/${this.currentType.id}/fields/${record.id}/`)
      .then(action(() => {
        this.fetchFields(this.currentType.id);
        this.fetchTypes();
      }));
  };
}

export default new TypeStore();
