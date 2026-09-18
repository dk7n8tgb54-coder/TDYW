/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行维护台账状态管理（步骤 3.2，MobX legacy decorators）。
 *
 * - LedgerStore 按 ledger_type 参数化，三类台账页面共用同一实现；
 * - TemplateStore / PointStore 为模板与巡检点管理页的独立 Store；
 * - 错误提示统一由 http 拦截器弹出，业务代码不重复提示。
 */
import {observable, action} from 'mobx';
import {http} from 'libs';
import {API_PREFIX_L} from './constants';

export class LedgerStore {
  ledgerType; // inspection | week_month | seasonal

  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_cycle = undefined; // 周月维护页筛选周/月
  @observable f_date_from = undefined;
  @observable f_date_to = undefined;

  @observable formVisible = false;
  @observable record = {};      // 编辑中的台账（草稿回填）
  @observable isSubmitting = false;

  @observable detailVisible = false;
  @observable detail = {};
  @observable isDetailFetching = false;

  constructor(ledgerType) {
    this.ledgerType = ledgerType;
  }

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_cycle = undefined;
    this.f_date_from = undefined;
    this.f_date_to = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize, ledger_type: this.ledgerType};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_cycle) params.maintenance_cycle = this.f_cycle;
    if (this.f_date_from) params.executed_from = this.f_date_from;
    if (this.f_date_to) params.executed_to = this.f_date_to;
    return http.get(`${API_PREFIX_L}/ledgers/`, {params})
      .then(action(res => {
        this.records = res.data;
        this.total = res.total;
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

  submitLedger = (id) => {
    return http.post(`${API_PREFIX_L}/ledgers/${id}/submit/`, {})
      .then(action(() => {
        this.fetchRecords();
      }));
  };

  voidLedger = (id, reason) => {
    return http.post(`${API_PREFIX_L}/ledgers/${id}/void/`, {reason})
      .then(action(() => {
        this.fetchRecords();
      }));
  };

  fetchDetail = (id) => {
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX_L}/ledgers/${id}/`)
      .then(action(res => {
        this.detail = res;
        this.detailVisible = true;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isDetailFetching = false;
      }));
  };

  closeDetail = action(() => {
    this.detailVisible = false;
    this.detail = {};
  });
}

export class TemplateStore {
  @observable records = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;

  f_ledger_type = undefined;
  f_keyword = undefined;

  @action setFilter = (key, value) => {
    this[key] = value;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {};
    if (this.f_ledger_type) params.ledger_type = this.f_ledger_type;
    if (this.f_keyword) params.keyword = this.f_keyword;
    return http.get(`${API_PREFIX_L}/ledger-templates/`, {params})
      .then(action(res => {
        this.records = res.data;
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

  toggleActive = (record, is_active) => {
    return http.put(`${API_PREFIX_L}/ledger-templates/${record.id}/active/`, {is_active})
      .then(action(() => {
        this.fetchRecords();
      }));
  };
}

export class PointStore {
  @observable records = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};
  @observable isSubmitting = false;

  f_keyword = undefined;
  f_system = undefined;
  systems = [];

  @action setFilter = (key, value) => {
    this[key] = value;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_system) params.system = this.f_system;
    return http.get(`${API_PREFIX_L}/inspection-points/`, {params})
      .then(action(res => {
        this.records = res.data;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isFetching = false;
      }));
  };

  fetchSystems = () => {
    return http.get(`${API_PREFIX_L}/systems/`, {params: {page: 1, page_size: 999}})
      .then(action(res => {
        this.systems = res.data;
      }))
      .catch(action(() => {}));
  };

  showForm = action((record = {}) => {
    this.record = record;
    this.formVisible = true;
  });

  toggleActive = (record, is_active) => {
    return http.put(`${API_PREFIX_L}/inspection-points/${record.id}/active/`, {is_active})
      .then(action(() => {
        this.fetchRecords();
      }));
  };
}

const ledgerStoreCache = {};

export function getLedgerStore(ledgerType) {
  if (!ledgerStoreCache[ledgerType]) {
    ledgerStoreCache[ledgerType] = new LedgerStore(ledgerType);
  }
  return ledgerStoreCache[ledgerType];
}

export const templateStore = new TemplateStore();
export const pointStore = new PointStore();
