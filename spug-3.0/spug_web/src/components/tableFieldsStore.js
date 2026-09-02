import http from '../libs/http';

const SETTING_KEY = 'table_fields';

class TableFieldsStore {
  fields = {};
  loaded = false;
  loading = null;
  ownerId = null;

  load() {
    const userId = sessionStorage.getItem('id');
    if (this.ownerId !== userId) {
      this.ownerId = userId;
      this.fields = {};
      this.loaded = false;
      this.loading = null;
    }
    if (this.loaded) return Promise.resolve(this.fields);
    if (!this.loading) {
      this.loading = http.get('/api/setting/user/')
        .then(settings => {
          this.loaded = true;
          try {
            const value = settings && settings[SETTING_KEY];
            this.fields = value ? (typeof value === 'string' ? JSON.parse(value) : value) : {};
          } catch (e) {
            this.fields = {};
          }
          return this.fields;
        })
        .catch(() => {
          this.loaded = true;
          return this.fields;
        });
    }
    return this.loading;
  }

  get(tKey) {
    return this.fields[tKey];
  }

  save() {
    this.ownerId = sessionStorage.getItem('id');
    const pendingFields = {...this.fields};
    return this.load().then(() => {
      this.fields = {...this.fields, ...pendingFields};
      return http.post('/api/setting/user/', {
      key: SETTING_KEY,
      value: JSON.stringify(this.fields),
      });
    }).catch(() => {});
  }
}

export default new TableFieldsStore();
