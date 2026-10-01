/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行维护台账状态管理（步骤 3.2，MobX legacy decorators）。
 *
 * - LedgerStore 按 ledger_type 参数化，两类台账页面共用同一实现；
 *   统一列表同时返回 Excel 模板台账与手工补录台账，Excel 详情由
 *   ExcelLedgerStore（excel/excelLedgerStore.js）独立承载；
 * - 旧可视化模板 TemplateStore 已随旧可视化模板路线删除（2026-10）；
 * - 错误提示统一由 http 拦截器弹出，业务代码不重复提示。
 */
import {observable, action} from 'mobx';
import {http} from 'libs';
import {API_PREFIX_L} from './constants';

export class LedgerStore {
  ledgerType; // week_month | seasonal

  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_date_from = undefined;
  @observable f_date_to = undefined;

  @observable detailVisible = false;
  @observable detail = {};
  @observable isDetailFetching = false;

  constructor(ledgerType) {
    this.ledgerType = ledgerType;
  }

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_date_from = undefined;
    this.f_date_to = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize, ledger_type: this.ledgerType};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
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

const ledgerStoreCache = {};

export function getLedgerStore(ledgerType) {
  if (!ledgerStoreCache[ledgerType]) {
    ledgerStoreCache[ledgerType] = new LedgerStore(ledgerType);
  }
  return ledgerStoreCache[ledgerType];
}
