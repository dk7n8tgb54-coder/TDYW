/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账 Store（2026-09-28 试点）。
 *
 * 状态：台账列表、当前台账详情（表头 + 版本快照 + 填写值）、可用模板版本。
 * 提交前本地先做必填校验（warning 提示，不发请求），后端仍独立校验；
 * 一键正常（2026-09-30）仅本地填充未填写的正常/异常格，不覆盖已填值；
 * 导出经公共 exportFile 二进制下载；PDF 导出先走预检接口（溢出/空白页/
 * 分页越界提示，确认后继续），默认使用版本快照参数，可传覆盖参数；
 * 复核/作废沿用既有 /ledgers 端点。
 */
import {observable, action, computed} from 'mobx';
import {message} from 'antd';
import {http, exportFile} from 'libs';

export const API = '/api/equipment-lifecycle/excel-ledgers';
export const LEDGER_API = '/api/equipment-lifecycle/ledgers';
export const TPL_AVAILABLE_API = '/api/equipment-lifecycle/excel-templates/available/';

export class ExcelLedgerStore {
  @observable list = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable filters = {};
  @observable loading = false;
  @observable detail = null;      // 台账详情（含 excel：version/values/editable）
  @observable values = {};        // field_id -> 填写值（编辑副本）
  @observable saving = false;
  @observable submitting = false;
  @observable creating = false;
  @observable available = [];     // 可用模板（含已发布版本）

  @computed get current() {
    return this.detail;
  }

  @computed get excel() {
    return this.detail ? (this.detail.excel || null) : null;
  }

  @computed get version() {
    return this.excel ? this.excel.version : null;
  }

  @computed get bindings() {
    return this.version ? (this.version.bindings || []) : [];
  }

  @computed get layout() {
    return this.version ? this.version.layout : null;
  }

  @computed get currentSheet() {
    if (!this.layout || !this.layout.sheets || !this.layout.sheets.length) return null;
    const active = (this.version && this.version.sheet_name) || this.layout.active_sheet;
    return this.layout.sheets.find(s => s.name === active)
      || this.layout.sheets[0] || null;
  }

  @computed get bindingByCell() {
    const map = {};
    this.bindings.forEach(b => {
      map[`${b.sheet_name}!${b.cell_coordinate}`] = b;
    });
    return map;
  }

  @computed get activeSheet() {
    const sheet = this.currentSheet;
    return sheet ? sheet.name : '';
  }

  @computed get editable() {
    return !!(this.excel && this.excel.editable);
  }

  @action applyDetail(detail) {
    const payload = detail && detail.data ? detail.data : detail;
    this.detail = payload;
    this.values = {...(payload && payload.excel ? payload.excel.values : {})};
  }

  async fetchList(filters) {
    this.loading = true;
    this.filters = filters || this.filters;
    try {
      const res = await http.get(`${API}/`, {params: {...this.filters, page: this.page, page_size: this.pageSize}});
      // 拦截器剥一层后：列表端点 res = {data: [...], total}；兼容双层包装
      const payload = res && res.data && !Array.isArray(res.data) && res.data.data
        ? res.data : res;
      this.list = (payload && payload.data) || [];
      this.total = (payload && payload.total) || 0;
    } finally {
      this.loading = false;
    }
  }

  @action setPage(page) {
    this.page = page;
    return this.fetchList();
  }

  @action setFilters(filters) {
    this.filters = {...filters};
    this.page = 1;
    return this.fetchList();
  }

  async fetchAvailable(ledgerType) {
    const res = await http.get(TPL_AVAILABLE_API,
      {params: ledgerType ? {ledger_type: ledgerType} : {}});
    const payload = res && res.data ? res.data : res;
    this.available = Array.isArray(payload) ? payload : [];
  }

  async createLedger(form) {
    this.creating = true;
    try {
      const res = await http.post(`${API}/`, {
        version_id: form.version_id,
        executed_date: form.executed_date,
        executor_names: form.executor_names || '',
        ledger_type: form.ledger_type || '',
        client_token: form.client_token || '',
      });
      this.applyDetail(res);
      message.success('台账已创建');
      return this.detail;
    } finally {
      this.creating = false;
    }
  }

  async fetchDetail(ledgerId) {
    this.loading = true;
    try {
      const res = await http.get(`${API}/${ledgerId}/`);
      this.applyDetail(res);
      return this.detail;
    } finally {
      this.loading = false;
    }
  }

  @action setValue(fieldId, value) {
    this.values = {...this.values, [fieldId]: value};
  }

  /**
   * 一键正常：仅填充未填写的「正常/异常」单元格（status 类型），不覆盖
   * 已填内容（含异常），文本/数值/日期/单选格不参与。纯本地填写，
   * 保存仍走既有 PUT 填写值接口，后端按候选独立校验。
   * 返回本次填充数量；没有可填项时 warning 并返回 0。
   */
  @action fillNormal() {
    const targets = this.bindings.filter(binding => {
      if (binding.input_type !== 'status') return false;
      const value = this.values[binding.field_id];
      return value === undefined || value === null || value === '';
    });
    if (!targets.length) {
      message.warning('没有未填写的正常/异常单元格');
      return 0;
    }
    const next = {...this.values};
    targets.forEach(binding => {
      next[binding.field_id] = '正常';
    });
    this.values = next;
    message.success(`已将 ${targets.length} 个未填写单元格填为正常，请检查后保存`);
    return targets.length;
  }

  async saveValues() {
    if (!this.detail) return;
    this.saving = true;
    try {
      const res = await http.put(`${API}/${this.detail.id}/`, {values: this.values});
      this.applyDetail(res);
      message.success('填写值已保存');
    } finally {
      this.saving = false;
    }
  }

  /**
   * 保存表头执行信息（实际执行日期/执行人；可编辑状态）。
   * 周期生成的应填台账执行日期为空，由填写人在执行后录入；
   * 提前生成不把创建当天伪装成实际维护日期。
   */
  async saveHeader(header) {
    if (!this.detail) return;
    this.saving = true;
    try {
      const res = await http.put(`${API}/${this.detail.id}/`, {header});
      this.applyDetail(res);
      message.success('执行信息已保存');
      return this.detail;
    } finally {
      this.saving = false;
    }
  }

  requiredMissing() {
    return this.bindings
      .filter(b => b.is_required)
      .filter(b => {
        const value = this.values[b.field_id];
        return value === undefined || value === null || value === '';
      })
      .map(b => b.field_name);
  }

  async submit() {
    this.submitting = true;
    try {
      const res = await http.post(`${API}/${this.detail.id}/submit/`);
      this.applyDetail(res);
      message.success('台账已提交');
    } finally {
      this.submitting = false;
    }
  }

  /** 复核沿用既有台账端点（提交 → 已复核；响应为普通详情形态，重取 Excel 详情）。 */
  async review() {
    await http.post(`${LEDGER_API}/${this.detail.id}/review/`);
    await this.fetchDetail(this.detail.id);
    message.success('已复核');
    return this.detail;
  }

  /** 作废沿用既有台账端点（须填原因；响应为普通详情形态，重取 Excel 详情）。 */
  async voidLedger(reason) {
    await http.post(`${LEDGER_API}/${this.detail.id}/void/`, {reason});
    await this.fetchDetail(this.detail.id);
    message.success('已作废');
    return this.detail;
  }

  _exportBaseName() {
    const version = this.version;
    const name = (version && version.source_filename) || '维护台账';
    return name.replace(/\.xlsx$/i, '');
  }

  exportExcel() {
    return exportFile({
      url: `${API}/${this.detail.id}/export/excel/`,
      method: 'post',
      defaultFilename: `${this._exportBaseName()}.excel.xlsx`,
      loadingText: '正在生成 Excel...',
    });
  }

  /**
   * 导出前预检：返回 warnings 提示列表（溢出/空白页/分页越界/必填）。
   * params 传入时按覆盖参数估算（与高级设置导出一致）；失败向上传递
   * （公共拦截器已提示，调用方不继续导出）。
   */
  async checkPdfExport(params) {
    const res = await http.post(`${API}/${this.detail.id}/export/check/`,
      params ? {pdf_params: params} : {});
    const payload = res && res.data ? res.data : res;
    return (payload && payload.warnings) || [];
  }

  /** 导出 PDF：默认用版本快照的模板参数；params 传入时覆盖（仅本次）。 */
  exportPdf(params) {
    return exportFile({
      url: `${API}/${this.detail.id}/export/pdf/`,
      method: 'post',
      data: params ? {pdf_params: params} : undefined,
      defaultFilename: `${this._exportBaseName()}.pdf.pdf`,
      timeout: 180000,
      loadingText: '正在转换 PDF...',
    });
  }
}

export default new ExcelLedgerStore();
