/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生路线维护台账 Store（2026-10-18 正式接入，规则与 Excel 路线对齐）。
 *
 * 状态：当前台账详情（表头 + 版本快照 + 填写值）、可用模板版本。
 * 填写值在编辑器 iframe 内编辑并经消息桥推送（applyEditorValues），
 * 保存前宿主再 collect 一次全量状态兜底（慢于推送的最后一次击键）；
 * 完成填写（草稿 → 已完成）先保存未保存修改再请求完成；已完成修改走
 * 更正（须填原因，后端记录前后值）；作废/删除沿用既有 /ledgers 端点；
 * 导出 PDF 走后端正式接口（服务端按版本快照渲染，必填未填被拦截）。
 */
import {observable, action, computed} from 'mobx';
import {message} from 'antd';
import {http, exportFile} from 'libs';

export const API = '/api/equipment-lifecycle/native-ledgers';
export const LEDGER_API = '/api/equipment-lifecycle/ledgers';
export const TPL_AVAILABLE_API = '/api/equipment-lifecycle/native-templates/available/';

/** 脏值比对快照：剔除未填写（undefined/null/空串）并排序键。 */
function _comparableValues(values) {
  const result = {};
  Object.keys(values || {}).sort().forEach(key => {
    const value = values[key];
    if (value === undefined || value === null || value === '') return;
    result[key] = value;
  });
  return result;
}

export class NativeLedgerStore {
  @observable detail = null;      // 台账详情（含 native：version/values/editable）
  @observable values = {};        // 绑定 key -> 填写值（编辑副本，来自编辑器推送）
  @observable savedValues = {};   // 最近一次保存成功的服务端值（脏值比对基线）
  @observable loading = false;
  @observable saving = false;
  @observable submitting = false;
  @observable creating = false;
  @observable exporting = false;
  @observable available = [];     // 可用原生模板（含已发布版本）
  @observable correcting = false; // 已完成台账更正模式
  @observable correctReason = ''; // 更正原因
  @observable editorValues = {};  // 编辑器最近一次推送的填写值（保存前兜底用）

  @computed get native() {
    return this.detail ? (this.detail.native || null) : null;
  }

  @computed get version() {
    return this.native ? this.native.version : null;
  }

  @computed get bindings() {
    return this.version ? (this.version.bindings || []) : [];
  }

  @computed get editable() {
    return !!(this.native && this.native.editable);
  }

  /** 更正模式下填写区可编辑（已完成台账；草稿走 editable）。 */
  @computed get correctingEditable() {
    return this.editable || this.correcting;
  }

  @action applyDetail(detail) {
    const payload = detail && detail.data ? detail.data : detail;
    this.detail = payload;
    this.values = {...(payload && payload.native ? payload.native.values : {})};
    this.savedValues = {...this.values};
    this.correcting = false;
    this.correctReason = '';
    this.editorValues = {};
  }

  @action applyEditorValues(payload) {
    this.editorValues = {...(payload.values || {})};
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
      const res = await http.post(`${API}/`, form);
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
      action(() => { this.loading = false; })();
    }
  }

  @computed get valuesDirty() {
    return JSON.stringify(_comparableValues(this.savedValues))
      !== JSON.stringify(_comparableValues(this.values));
  }

  /** 未保存修改（草稿或更正模式）：填写值有未保存修改。 */
  @computed get hasUnsaved() {
    if (!this.detail || (!this.editable && !this.correcting)) return false;
    return this.valuesDirty;
  }

  _saveSuccessText() {
    return '填写值已保存';
  }

  /**
   * 把未保存修改（填写值）一次 PUT 保存成功；无未保存修改时不发请求。
   * editorState 为编辑器 collect 的最新值（保存前兜底）；
   * collect 失败时退回最近一次推送值（editorValues，可能有 <250ms 延迟）。
   */
  async _savePendingChanges(editorState) {
    if (editorState && typeof editorState.values === 'object') {
      this.values = {...this.values, ...editorState.values};
    }
    if (!this.valuesDirty) return this.detail;
    const body = {values: this.values};
    const res = await http.put(`${API}/${this.detail.id}/`, body);
    this.applyDetail(res);
    return this.detail;
  }

  /** 收集编辑器最新填写值；失败退回最近推送值（不阻断保存）。 */
  async _collectEditorState(collect) {
    if (!collect) return null;
    try {
      return await collect();
    } catch (e) {
      return this.editorValues && Object.keys(this.editorValues).length
        ? {values: this.editorValues} : null;
    }
  }

  /** 保存草稿：先 collect 编辑器最新填写值再保存；成功后通知编辑器复位脏标记。 */
  async saveValues(collect, notifySaved) {
    if (!this.detail || this.saving || this.submitting) return;
    this.saving = true;
    try {
      await this._savePendingChanges(await this._collectEditorState(collect));
      message.success(this._saveSuccessText());
      notifySaved && notifySaved();
    } finally {
      action(() => { this.saving = false; })();
    }
  }

  requiredMissing() {
    return this.bindings
      .filter(b => b.is_required)
      .filter(b => {
        const value = this.values[b.key];
        return value === undefined || value === null || value === '';
      })
      .map(b => b.label);
  }

  /**
   * 完成填写（流程终点）：先保存未保存修改，再请求完成（草稿 → 已完成）。
   * 必填项本地预检仅提醒，服务端完成后仍终验。
   */
  async complete(collect, notifySaved) {
    if (!this.detail || this.saving || this.submitting) return;
    this.submitting = true;
    try {
      await this._savePendingChanges(await this._collectEditorState(collect));
      const res = await http.post(`${API}/${this.detail.id}/complete/`);
      this.applyDetail(res);
      message.success('已完成填写');
      notifySaved && notifySaved();
    } finally {
      action(() => { this.submitting = false; })();
    }
  }

  // ==================== 已完成台账更正 ====================

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
  async submitCorrection(collect) {
    if (!this.detail || !this.correcting) return;
    this.saving = true;
    try {
      let currentValues = {...this.values};
      const editorState = await this._collectEditorState(collect);
      if (editorState && typeof editorState.values === 'object') {
        currentValues = {...currentValues, ...(editorState.values || {})};
      }
      const body = {reason: this.correctReason, values: currentValues};
      const res = await http.post(`${API}/${this.detail.id}/correct/`, body);
      this.applyDetail(res);
      message.success('更正已保存');
      return this.detail;
    } finally {
      action(() => { this.saving = false; })();
    }
  }

  /** 物理删除台账（草稿；已完成与已作废由后端拒绝）。 */
  async deleteLedger() {
    if (!this.detail) return;
    await http.delete(`${LEDGER_API}/${this.detail.id}/`);
  }

  /** 作废沿用既有台账端点（须填原因；响应为普通详情形态，重取原生详情）。 */
  async voidLedger(reason) {
    await http.post(`${LEDGER_API}/${this.detail.id}/void/`, {reason});
    await this.fetchDetail(this.detail.id);
    message.success('已作废');
    return this.detail;
  }

  _exportBaseName() {
    const version = this.version;
    const name = (version && version.template_name) || '维护台账';
    return name || '维护台账';
  }

  /** 导出 PDF（后端按台账引用版本快照 + 填写值渲染；必填未填被后端拦截）。 */
  exportPdf() {
    return exportFile({
      url: `${API}/${this.detail.id}/export/pdf/`,
      method: 'post',
      defaultFilename: `${this._exportBaseName()}.pdf.pdf`,
      timeout: 180000,
      loadingText: '正在生成 PDF...',
    });
  }
}

export default new NativeLedgerStore();
