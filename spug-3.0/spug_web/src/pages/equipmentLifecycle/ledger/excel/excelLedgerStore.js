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
 * 并发防护（2026-10-26）：写操作互斥守卫；fetchDetail 序列守卫防翻阅
 * 竞态（旧响应不得覆盖新台账）；保存/更正携带乐观锁令牌
 * expected_version（详情顶层 version 为基线，缺省不带，后端不校验）。
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
  savedVersion = undefined;       // 乐观锁令牌基线（详情顶层 version；缺省则请求不带）
  detailLoadSeq = 0;              // 详情请求序列（翻阅竞态守卫：仅最新响应可落地）
  @observable saving = false;
  @observable submitting = false;
  @observable creating = false;
  @observable available = [];     // 可用模板（含已发布版本）
  @observable correcting = false; // 已完成台账更正模式（修改后整体提交，须填原因）
  @observable correctReason = ''; // 更正原因（进入更正模式时必填）
  @observable activeSheetName = ''; // 填写视图当前工作表（'' = 主工作表）
  // 打印预览（2026-10-21）：与导出 PDF 同一生成服务的 inline 预览
  @observable printPreviewUrl = '';   // blob 对象 URL（iframe 展示）
  @observable printPreviewMeta = null; // {pages, paper}（X-El-Pdf-* 反馈头）
  @observable printPreviewLoading = false;
  @observable printPreviewError = '';

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

  /**
   * 填写区可编辑：完成/更正提交在途时锁定——这两类请求成功后以服务端
   * 详情整体重置 values，在途输入会被静默丢弃（普通保存不重置编辑副本，
   * 保存期间仍可继续输入）。
   */
  @computed get fillEditable() {
    if (!this.correctingEditable) return false;
    if (this.submitting) return false;
    if (this.correcting && this.saving) return false;
    return true;
  }

  @action applyDetail(detail) {
    const payload = detail && detail.data ? detail.data : detail;
    if (!payload) {
      // 返回列表/退出翻阅：使在途详情请求失效——否则详情关闭后旧响应
      // 落地仍会 applyDetail 胜出，把已退出的台账重新打开
      this.detailLoadSeq += 1;
      this.loading = false;
    }
    this.detail = payload;
    this.values = {...(payload && payload.excel ? payload.excel.values : {})};
    // 服务端真值即脏值比对基线；
    // 更正模式随详情刷新退出（是否更正成功以服务端详情为准）
    this.savedValues = {...this.values};
    // 乐观锁基线：详情/完成/更正响应统一从顶层 version 更新；
    // 旧后端/测试 mock 无 version 时置 undefined（保存/更正请求缺省不带令牌）
    this.savedVersion = payload ? payload.version : undefined;
    this.correcting = false;
    this.correctReason = '';
    // 切换台账详情回到主工作表（手选工作表不跨详情残留）
    this.activeSheetName = '';
    // 预览属于上一张台账，切换详情即失效（blob URL 一并释放）
    this.resetPrintPreview();
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
    // 竞态守卫（翻阅快速连点）：发起时取序列号，响应落地前已有更新的
    // 详情请求则本响应整体丢弃——旧详情不得覆盖新台账（否则后续保存
    // PUT 会发往错误台账 id）
    const seq = ++this.detailLoadSeq;
    action(() => { this.loading = true; })();
    try {
      const res = await http.get(`${API}/${ledgerId}/`);
      if (seq !== this.detailLoadSeq) return this.detail;
      this.applyDetail(res);
      return this.detail;
    } finally {
      // 仅最新请求负责复位 loading（被取代的旧请求不复位，避免提前
      // 关掉新请求的加载态）。action 包裹：详情请求完成后 loading 复位
      // 必须触发订阅者重渲染（裸写在渲染调度竞态下会让详情卡加载态
      // 永久定格，2026-10-17 实机缺陷）
      if (seq === this.detailLoadSeq) {
        action(() => { this.loading = false; })();
      }
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
   * 携带乐观锁令牌 expected_version（详情顶层 version 为基线，缺省不带）。
   * 成功后只更新详情与保存基线（已保存部分不再算脏），编辑副本 values
   * 不整体重置——PUT 在途期间用户的新输入保留、仍如实显示未保存
   * （完成/更正后的 applyDetail 重置保留：完成后转只读是合理语义）。
   * 失败向上抛出（拦截器已提示），页面内容不受影响。
   */
  async _savePendingChanges(options = {}) {
    if (!this.valuesDirty) return this.detail;
    const ledgerId = this.detail.id;
    const body = {values: this.values};
    if (this.savedVersion !== undefined && this.savedVersion !== null) {
      body.expected_version = this.savedVersion;
    }
    const res = await http.put(`${API}/${ledgerId}/`, body);
    const payload = res && res.data ? res.data : res;
    // 保存在途期间返回列表/切换详情：旧响应不写回（否则刚关闭的台账被
    // 重新打开，或覆盖已切换的新详情）；服务端已保存，重新打开该台账
    // 时按库内最新值展示
    if (!this.detail || this.detail.id !== ledgerId) return null;
    const values = payload && payload.excel ? payload.excel.values : this.values;
    action(() => {
      this.detail = payload;
      this.savedValues = {...(values || {})};
      if (payload && payload.version !== undefined && payload.version !== null) {
        this.savedVersion = payload.version;
      }
      // 保存后服务端数据已变，旧打印预览失效（与 applyDetail 同一口径）
      this.resetPrintPreview();
    })();
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
    const ledgerId = this.detail.id;
    this.submitting = true;
    try {
      await this._savePendingChanges();
      // 保存在途期间返回列表/切换详情：本台账的完成流程终止（内层保存
      // 响应已按 id 守卫丢弃，不得对已关闭/已切换的详情继续完成）
      if (!this.detail || this.detail.id !== ledgerId) return;
      const res = await http.post(`${API}/${ledgerId}/complete/`);
      // 完成请求在途期间返回列表：响应落地不得把已关闭的详情重新打开
      if (!this.detail || this.detail.id !== ledgerId) return;
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
   * 与保存/完成互斥：进行中重复调用直接忽略（防止重复点击与并发处理）。
   */
  async submitCorrection() {
    if (!this.detail || !this.correcting || this.saving || this.submitting) return;
    const ledgerId = this.detail.id;
    this.saving = true;
    try {
      const body = {reason: this.correctReason, values: this.values};
      if (this.savedVersion !== undefined && this.savedVersion !== null) {
        body.expected_version = this.savedVersion;
      }
      const res = await http.post(`${API}/${ledgerId}/correct/`, body);
      // 更正请求在途期间返回列表：响应落地不得把已关闭的详情重新打开
      if (!this.detail || this.detail.id !== ledgerId) return null;
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

  // ==================== 打印预览（2026-10-21 统一打印布局） ====================

  _revokePreviewUrl() {
    if (this.printPreviewUrl) {
      try {
        window.URL.revokeObjectURL(this.printPreviewUrl);
      } catch (e) {
        // URL 已释放时忽略
      }
    }
  }

  /** 重置预览（切换台账/详情刷新时调用；blob URL 释放防泄漏）。 */
  @action resetPrintPreview() {
    this._revokePreviewUrl();
    this.printPreviewUrl = '';
    this.printPreviewMeta = null;
    this.printPreviewError = '';
  }

  /**
   * 拉取打印预览 PDF（POST print-preview/，arraybuffer）：与导出 PDF
   * 同一后端生成服务与同一模板级参数，保证「预览 = 下载」；填写值取
   * 最近一次保存的服务端值（未保存修改由页面横幅明确提示）。
   * 成功返回 blob URL 并记录 X-El-Pdf-Pages/Paper 反馈头；失败向上抛出
   * （公共拦截器已提示业务错误），页面显示失败态可重试。
   * await 后的可观察变更用 action 包裹（mobx legacy 装饰器只包同步段，
   * 与本 store 既有 fetchDetail/fetchList 同一约定）。
   */
  async fetchPrintPreview() {
    if (!this.detail || this.printPreviewLoading) return '';
    action(() => {
      this.printPreviewLoading = true;
      this.printPreviewError = '';
    })();
    try {
      const response = await http.post(
        `${API}/${this.detail.id}/print-preview/`, {},
        {responseType: 'arraybuffer', timeout: 180000});
      const bytes = response && response.data;
      if (!bytes || !bytes.byteLength) {
        throw new Error('预览内容为空');
      }
      const headers = (response && response.headers) || {};
      const meta = {
        pages: headers['x-el-pdf-pages'] || '',
        paper: headers['x-el-pdf-paper'] || '',
      };
      const blob = new Blob([bytes], {type: 'application/pdf'});
      const url = window.URL.createObjectURL(blob);
      this._revokePreviewUrl();
      return action(() => {
        this.printPreviewUrl = url;
        this.printPreviewMeta = meta;
        return url;
      })();
    } catch (e) {
      action(() => {
        this.printPreviewError = '预览生成失败，可点击「刷新预览」重试或直接导出 PDF';
      })();
      throw e;
    } finally {
      action(() => { this.printPreviewLoading = false; })();
    }
  }
}

export default new ExcelLedgerStore();
