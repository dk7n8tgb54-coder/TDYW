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
 * - 周期分组（2026-10-11）：fetchGroups 按 维护类型+周期 拉取分组列表，
 *   batchCreate 一键新增周期台账（后端幂等去重并返回实际新增/已存在数），
 *   fetchSystemOptions 提供"按系统查看"筛选与批量新增范围展示；
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
  @observable f_system = undefined;
  @observable f_date_from = undefined;
  @observable f_date_to = undefined;

  @observable groups = [];
  @observable groupsVersion = 0; // 自增键：分组表格 remount 后默认展开最新分组
  @observable isGroupsFetching = false;
  @observable systemOptions = [];

  @observable detailVisible = false;
  @observable detail = {};
  @observable isDetailFetching = false;

  constructor(ledgerType) {
    this.ledgerType = ledgerType;
  }

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_system = undefined;
    this.f_date_from = undefined;
    this.f_date_to = undefined;
    this.page = 1;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize, ledger_type: this.ledgerType};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
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

  fetchGroups = () => {
    this.isGroupsFetching = true;
    const params = {ledger_type: this.ledgerType};
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
    if (this.f_keyword) params.keyword = this.f_keyword;
    return http.get(`${API_PREFIX_L}/ledgers/period-groups/`, {params})
      .then(action(res => {
        this.groups = (res && res.data) || [];
        this.groupsVersion += 1;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isGroupsFetching = false;
      }));
  };

  fetchSystemOptions = () => {
    return http.get(`${API_PREFIX_L}/ledgers/batch-create/`)
      .then(action(res => {
        this.systemOptions = (res && res.data) || [];
      }))
      .catch(action(() => {}));
  };

  batchCreate = (payload) => {
    return http.post(`${API_PREFIX_L}/ledgers/batch-create/`, payload)
      .then(action(res => {
        this.fetchGroups();
        return res;
      }));
  };

  submitLedger = (id) => {
    return http.post(`${API_PREFIX_L}/ledgers/${id}/submit/`, {})
      .then(action(() => {
        this.fetchGroups();
      }));
  };

  voidLedger = (id, reason) => {
    return http.post(`${API_PREFIX_L}/ledgers/${id}/void/`, {reason})
      .then(action(() => {
        this.fetchGroups();
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
