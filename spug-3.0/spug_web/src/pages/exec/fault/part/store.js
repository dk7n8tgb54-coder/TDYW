import { observable, computed } from 'mobx';
import http from 'libs/http';

class Store {
  @observable records = [];
  @observable system_names = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};
  @observable f_name;
  @observable f_system;
  @observable f_status;

  get dataSource() {
    let data = this.records;
    if (this.f_name) data = data.filter(x => x.name.includes(this.f_name));
    if (this.f_system) data = data.filter(x => x.system_name === this.f_system);
    if (this.f_status) data = data.filter(x => x.status === this.f_status);
    return data;
  }

  @computed get statusOptions() {
    return ['故障', '送修', '运回测试', '正常归档'];
  }

  fetchRecords = () => {
    this.isFetching = true;
    return http.get('/api/fault/faultpart/')
      .then(res => {
        this.records = res.records;
        this.system_names = res.system_names;
      })
      .finally(() => {
        this.isFetching = false;
      });
  }

  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = { ...info };
  }

  handleSubmit = (values) => {
    const data = { ...values };
    return http.post('/api/fault/faultpart/', data)
      .then(() => {
        this.formVisible = false;
        this.fetchRecords();
      });
  }

  handleDelete = (record) => {
    return http.delete('/api/fault/faultpart/', { params: { id: record.id } })
      .then(() => this.fetchRecords());
  }
}

export default new Store();
