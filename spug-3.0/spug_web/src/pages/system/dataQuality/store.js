import { observable } from 'mobx';
import { http } from 'libs';

class Store {
  @observable loading = false;
  @observable results = null;

  runCheck = () => {
    this.loading = true;
    return http.get('/api/alert/data-quality/')
      .then(res => {
        this.results = res;
      })
      .finally(() => {
        this.loading = false;
      });
  };
}

export default new Store();
