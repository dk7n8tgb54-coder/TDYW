/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账 Store（2026-09-28 试点）。
 *
 * 状态：台账列表、当前台账详情（表头 + 版本快照 + 填写值）、可用模板版本。
 * 完成填写（2026-10-16 流程简化，原"保存并提交"）：先把未保存的填写值
 * 保存成功，再请求完成（草稿 → 已完成），带脏值跟踪
 * （values vs savedValues）供返回列表前未保存提示；
 * 已完成台账更正：进入更正模式（须填原因）后可修改填写值，
 * 提交更正走 /correct/（后端记录修改人/时间/前后值），再次修改留痕；
 * 一键正常（2026-09-30）仅本地填充未填写的正常/异常格，不覆盖已填值；
 * 导出经公共 exportFile 二进制下载；PDF 导出先走预检接口（溢出/空白页/
 * 分页越界提示，确认后继续），默认使用版本快照参数，可传覆盖参数；
 * 作废/删除沿用既有 /ledgers 端点（删除仅草稿与旧流程历史状态）。
 */
import {observable, action, computed} from 'mobx';
import {message} from 'antd';
import {http, exportFile} from 'libs';

export const API = '/api/equipment-lifecycle/excel-ledgers';
export const LEDGER_API = '/api/equipment-lifecycle/ledgers';
export const TPL_AVAILABLE_API = '/api/equipment-lifecycle/excel-templates/available/';

/** 脏值比对快照：剔除未填写（undefined/null/空串）并排序键，避免键序干扰。 */
function _comparableValues(values) {
  const result = {};
  Object.keys(values || {}).sort().forEach(key => {
    const value = values[key];
    if (value === undefined || value === null || value === '') return;
    result[key] = value;
  });
  return result;
}

/** 未填写判定（与后端完成校验 not values.get(field_id) 同口径：填写值
 * 均为字符串，空串/缺省即未填）。 */
function _isUnfilled(value) {
  return value === undefined || value === null || value === '';
}

export class ExcelLedgerStore {
  @observable list = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable filters = {};
  @observable loading = false;
  @observable detail = null;      // 台账详情（含 excel：version/values/editable）
  @observable values = {};        // field_id -> 填写值（编辑副本）
  @observable savedValues = {};   // 最近一次保存成功的服务端值（脏值比对基线）
  @observable saving = false;
  @observable submitting = false;
  @observable creating = false;
  @observable available = [];     // 可用模板（含已发布版本）
  @observable correcting = false; // 已完成台账更正模式（修改后整体提交，须填原因）
  @observable correctReason = ''; // 更正原因（进入更正模式时必填）
  @observable activeSheetName = ''; // 填写视图当前工作表（'' = 主工作表）

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
    const fallback = (this.version && this.version.sheet_name) || this.layout.active_sheet;
    const name = this.activeSheetName || fallback;
    // 手选工作表优先；手选名失效（如详情切换）回落主工作表
    return this.layout.sheets.find(s => s.name === name)
      || this.layout.sheets.find(s => s.name === fallback)
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

  /** 切换填写视图工作表（多工作表模板；空串回落主工作表）。 */
  @action setSheet(name) {
    this.activeSheetName = name || '';
  }

  /** 填写进度（与完成填写必填校验同口径）：总数/已填/必填总数/必填已填。 */
  @computed get fillProgress() {
    let filled = 0;
    this.bindings.forEach(b => {
      if (!_isUnfilled(this.values[b.field_id])) filled += 1;
    });
    const required = this.bindings.filter(b => b.is_required);
    const requiredFilled = required.filter(b => !_isUnfilled(this.values[b.field_id])).length;
    return {
      total: this.bindings.length, filled,
      requiredTotal: required.length, requiredFilled,
    };
  }

  /** 未填写的必填字段（bindings 原序）：必填校验提示与填写导航共用此来源，
   * 保证导航进度与提交校验不会出现两套口径。 */
  @computed get missingRequiredBindings() {
    return this.bindings.filter(b => b.is_required && _isUnfilled(this.values[b.field_id]));
  }

  /** 按工作表组织的绑定清单（保持 layout.sheets 顺序，只含有绑定的工作表）。 */
  @computed get bindingsBySheet() {
    const groups = [];
    const byName = {};
    ((this.layout && this.layout.sheets) || []).forEach(sheet => {
      const item = {name: sheet.name, bindings: []};
      byName[sheet.name] = item;
      groups.push(item);
    });
    this.bindings.forEach(b => {
      if (byName[b.sheet_name]) byName[b.sheet_name].bindings.push(b);
    });
    return groups.filter(group => group.bindings.length);
  }

  @computed get editable() {
    return !!(this.excel && this.excel.editable);
  }

  /** 更正模式下填写区可编辑（已完成台账；草稿走 editable）。 */
  @computed get correctingEditable() {
    return this.editable || this.correcting;
  }

  @action applyDetail(detail) {
    const payload = detail && detail.data ? detail.data : detail;
    this.detail = payload;
    this.values = {...(payload && payload.excel ? payload.excel.values : {})};
    // 服务端真值即脏值比对基线；
    // 更正模式随详情刷新退出（是否更正成功以服务端详情为准）
    this.savedValues = {...this.values};
    this.correcting = false;
    this.correctReason = '';
    // 切换台账详情回到主工作表（手选工作表不跨详情残留）
    this.activeSheetName = '';
  }

  async fetchList(filters) {
    action(() => {
      this.loading = true;
      this.filters = filters || this.filters;
    })();
    try {
      const res = await http.get(`${API}/`, {params: {...this.filters, page: this.page, page_size: this.pageSize}});
      // 拦截器剥一层后：列表端点 res = {data: [...], total}；兼容双层包装
      const payload = res && res.data && !Array.isArray(res.data) && res.data.data
        ? res.data : res;
      action(() => {
        this.list = (payload && payload.data) || [];
        this.total = (payload && payload.total) || 0;
      })();
    } finally {
      action(() => { this.loading = false; })();
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
        ledger_type: form.ledger_type || '',
        client_token: form.client_token || '',
      });
      this.applyDetail(res);
      message.success('台账已创建');
      return this.detail;
    } finally {
      action(() => { this.creating = false; })();
    }
  }

  async fetchDetail(ledgerId) {
    action(() => { this.loading = true; })();
    try {
      const res = await http.get(`${API}/${ledgerId}/`);
      this.applyDetail(res);
      return this.detail;
    } finally {
      // action 包裹：详情请求完成后 loading 复位必须触发订阅者重渲染
      // （裸写在渲染调度竞态下会让详情卡加载态永久定格，2026-10-17 实机缺陷）
      action(() => { this.loading = false; })();
    }
  }

  @action setValue(fieldId, value) {
    this.values = {...this.values, [fieldId]: value};
  }

  /** 未保存修改（草稿或更正模式）：填写值有未保存修改。 */
  @computed get hasUnsaved() {
    if (!this.detail || (!this.editable && !this.correcting)) return false;
    return this.valuesDirty;
  }

  @computed get valuesDirty() {
    return JSON.stringify(_comparableValues(this.savedValues))
      !== JSON.stringify(_comparableValues(this.values));
  }

  /** 保存成功提示文案。 */
  _saveSuccessText() {
    return '填写值已保存';
  }

  /**
   * 把未保存修改（填写值）一次 PUT 保存成功；无未保存修改时不发请求。
   * 失败向上抛出（拦截器已提示），页面内容不受影响。
   */
  async _savePendingChanges(options = {}) {
    if (!this.valuesDirty) return this.detail;
    const body = {values: this.values};
    const res = await http.put(`${API}/${this.detail.id}/`, body);
    this.applyDetail(res);
    if (options.successText) message.success(options.successText);
    return this.detail;
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

  /**
   * 保存草稿（次操作）：保存未保存的填写值，一次请求；
   * 保存中/提交中重复点击忽略。
   */
  async saveValues() {
    if (!this.detail || this.saving || this.submitting) return;
    this.saving = true;
    try {
      await this._savePendingChanges({successText: this._saveSuccessText()});
    } finally {
      action(() => { this.saving = false; })();
    }
  }

  /** 必填缺失字段名（与 missingRequiredBindings 同源，口径不再分叉）。 */
  requiredMissing() {
    return this.missingRequiredBindings.map(b => b.field_name);
  }

  /**
   * 完成填写（主操作，流程终点）：先把未保存的填写值保存
   * 成功，再请求完成（草稿 → 已完成）；任一步失败向上抛出（拦截器已提示），
   * 不显示完成成功、不丢弃页面内容。保存中/完成中重复调用直接忽略，
   * 防止重复点击与并发处理；成功提示只出现一次（已完成填写）。
   * 必填项的本地预检仅作提醒，服务端完成后仍终验（返回详情以服务端为准）。
   */
  async complete() {
    if (!this.detail || this.saving || this.submitting) return;
    this.submitting = true;
    try {
      await this._savePendingChanges();
      const res = await http.post(`${API}/${this.detail.id}/complete/`);
      this.applyDetail(res);
      message.success('已完成填写');
    } finally {
      action(() => { this.submitting = false; })();
    }
  }

  // ==================== 已完成台账更正（2026-10-16） ====================

  /** 进入更正模式（原因已在弹窗确认时校验非空）。 */
  @action startCorrection(reason) {
    this.correcting = true;
    this.correctReason = reason;
  }

  /** 取消更正：恢复为服务端已保存值，退出更正模式。 */
  @action cancelCorrection() {
    this.values = {...this.savedValues};
    this.correcting = false;
    this.correctReason = '';
  }

  /**
   * 提交更正：整体提交当前填写值 + 原因，后端记录修改人/时间/
   * 前后值并生成更正记录；成功后以服务端详情为准（更正模式自动退出）。
   */
  async submitCorrection() {
    if (!this.detail || !this.correcting) return;
    this.saving = true;
    try {
      const body = {reason: this.correctReason, values: this.values};
      const res = await http.post(`${API}/${this.detail.id}/correct/`, body);
      this.applyDetail(res);
      message.success('更正已保存');
      return this.detail;
    } finally {
      action(() => { this.saving = false; })();
    }
  }

  /** 物理删除台账（草稿/旧流程历史状态；已完成与已作废由后端拒绝）。 */
  async deleteLedger() {
    if (!this.detail) return;
    await http.delete(`${LEDGER_API}/${this.detail.id}/`);
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
