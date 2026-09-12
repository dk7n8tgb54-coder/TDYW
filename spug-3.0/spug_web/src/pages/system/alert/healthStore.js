import { observable } from 'mobx';
import { http } from 'libs';

class HealthStore {
  @observable loading = false;
  @observable hours = 48;
  @observable items = [];
  @observable summary = [];
  @observable state = 'unknown';

  fetch = () => {
    this.loading = true;
    return Promise.all([
      http.get('/api/alert/run-metrics/', {params: {hours: this.hours}}),
      http.get('/api/alert/run-metrics/summary/', {params: {days: 7}}),
    ]).then(([trend, summary]) => {
      this.items = trend.items || [];
      this.state = trend.state || 'unknown';
      this.summary = summary.items || [];
    }).finally(() => {
      this.loading = false;
    });
  };

  setHours = hours => {
    this.hours = hours;
    return this.fetch();
  };
}

export default new HealthStore();
