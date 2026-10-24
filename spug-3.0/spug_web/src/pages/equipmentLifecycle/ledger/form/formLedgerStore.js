/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单路线台账 Store（2026-10-21，与 excelLedgerStore 同构）。
 *
 * 状态：当前详情（表头 + form：版本快照/表单定义/填写值）、编辑副本 values、
 * 可用模板。完成填写先保存未保存值再请求完成（后端必填终验），带脏值跟踪
 * （values vs savedValues）供返回列表前未保存提示；
 * 作废/删除沿用既有 /ledgers 端点（列表操作列），本 Store 不重复实现。
 * 编辑动作（setField/addRow/setMatrixCell 等）由 FormFillRenderer 的
 * onEdit 统一分发到这里的 action。
 */
import {observable, action, computed} from 'mobx';
import {message} from 'antd';
import {http, exportFile} from 'libs';
import {applyFillEdit} from './FormFillRenderer';

export const API = '/api/equipment-lifecycle/form-ledgers';
export const TPL_AVAILABLE_API = '/api/equipment-lifecycle/form-templates/available/';

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

export class FormLedgerStore {
  @observable detail = null;      // 台账详情（含 form：version/values/editable）
  @observable values = {};        // 编辑副本（field_id -> 值，含明细组/矩阵结构）
  @observable savedValues = {};   // 最近一次保存成功的服务端值（脏值比对基线）
  @observable loading = false;
  @observable saving = false;
  @observable submitting = false;
  @observable creating = false;
  @observable available = [];     // 可用数字表单模板（含当前在用版本）
  // PDF 预览/导出（2026-10-22）：预览与下载调用同一后端生成函数
  @observable pdfPreviewUrl = '';     // blob 对象 URL（弹窗 iframe 展示）
  @observable pdfPreviewMeta = null;  // {pages, paper}（X-El-Pdf-* 反馈头）
  @observable pdfPreviewLoading = false;
  @observable pdfPreviewError = '';
  @observable exportingPdf = false;

  @action applyDetail(res) {
    const payload = res && res.data ? res.data : res;
    this.detail = payload;
    const values = payload && payload.form ? payload.form.values : {};
    this.values = {...(values || {})};
    this.savedValues = {...(values || {})};
    // 详情刷新（含保存/完成后回写）使旧预览失效：PDF 必须基于已保存数据
    this.invalidatePdfPreview();
  }

  /** 旧 PDF 预览失效（详情回写/保存成功后调用）：释放 blob URL 防陈旧展示。 */
  @action invalidatePdfPreview() {
    if (this.pdfPreviewUrl) {
      window.URL.revokeObjectURL(this.pdfPreviewUrl);
      this.pdfPreviewUrl = '';
    }
    this.pdfPreviewMeta = null;
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
      // （与 excelLedgerStore 同一竞态防御，2026-10-17 实机缺陷）
      action(() => { this.loading = false; })();
    }
  }

  // —— 编辑动作（FormFillRenderer onEdit 分发目标） ——
  // 不可变更新逻辑在 applyFillEdit 纯函数（2026-10-23 提炼，与试填预览共用）

  @action edit(kind, ...args) {
    this.values = applyFillEdit(this.values, kind, ...args);
  }

  @computed get valuesDirty() {
    return JSON.stringify(_comparableValues(this.savedValues))
      !== JSON.stringify(_comparableValues(this.values));
  }

  /** 未保存修改（仅草稿可编辑时参与工作页签保护）。 */
  @computed get hasUnsaved() {
    if (!this.detail || !this.editable) return false;
    return this.valuesDirty;
  }

  @computed get editable() {
    return !!(this.detail && this.detail.form && this.detail.form.editable);
  }

  @computed get formStructure() {
    return (this.detail && this.detail.form && this.detail.form.version.form) || {groups: []};
  }

  async saveValues() {
    if (!this.valuesDirty) return;
    this.saving = true;
    try {
      const res = await http.put(`${API}/${this.detail.id}/`, {values: this.values});
      const payload = res && res.data ? res.data : res;
      const values = payload && payload.form ? payload.form.values : this.values;
      this.savedValues = {...(values || {})};
      this.detail = payload;
      // 保存成功即旧预览过期（PDF 只反映已保存数据）
      this.invalidatePdfPreview();
      message.success('填写内容已保存');
    } finally {
      action(() => { this.saving = false; })();
    }
  }

  /** 完成填写：先保存未保存内容（保存失败不进入完成），后端做必填终验。 */
  async complete() {
    this.submitting = true;
    try {
      if (this.valuesDirty) {
        await this.saveValues();
      }
      const res = await http.post(`${API}/${this.detail.id}/complete/`, {source: 'form-detail'});
      this.applyDetail(res);
      message.success('台账已完成');
      return this.detail;
    } finally {
      action(() => { this.submitting = false; })();
    }
  }

  // —— PDF 预览 / 导出（与后端同一生成函数，预览 = 下载） ——

  _revokePdfPreviewUrl() {
    if (this.pdfPreviewUrl) {
      window.URL.revokeObjectURL(this.pdfPreviewUrl);
      this.pdfPreviewUrl = '';
    }
  }

  /** 关闭/重置预览（blob URL 释放防泄漏）。 */
  @action closePdfPreview() {
    this._revokePdfPreviewUrl();
    this.pdfPreviewMeta = null;
    this.pdfPreviewError = '';
    this.pdfPreviewLoading = false;
  }

  /**
   * 拉取预览 PDF（POST preview/pdf/，arraybuffer）：与导出同一后端生成
   * 函数；填写值取最近一次保存的服务端值（未保存修改由页面确认弹窗
   * 明确提示）。成功返回 blob URL 并记录 X-El-Pdf-Pages/Paper 反馈头；
   * 失败向上抛出（公共拦截器已提示业务错误），弹窗显示失败态可重试。
   * await 后的可观察变更用 action 包裹（mobx legacy 装饰器只包同步段）。
   */
  async fetchPdfPreview() {
    if (!this.detail || this.pdfPreviewLoading) return '';
    action(() => {
      this.pdfPreviewLoading = true;
      this.pdfPreviewError = '';
    })();
    try {
      const response = await http.post(
        `${API}/${this.detail.id}/preview/pdf/`, {},
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
      this._revokePdfPreviewUrl();
      return action(() => {
        this.pdfPreviewUrl = url;
        this.pdfPreviewMeta = meta;
        return url;
      })();
    } catch (e) {
      action(() => {
        this.pdfPreviewError = '预览生成失败，可点击「重新生成」重试或直接导出 PDF';
      })();
      throw e;
    } finally {
      action(() => { this.pdfPreviewLoading = false; })();
    }
  }

  /** 导出 PDF（附件下载；exportFile 统一解析文件名/触发浏览器下载）。 */
  async exportPdf() {
    if (!this.detail || this.exportingPdf) return;
    this.exportingPdf = true;
    try {
      await exportFile({
        url: `${API}/${this.detail.id}/export/pdf/`,
        method: 'post',
        data: {},
        defaultFilename: '数字表单台账.pdf',
        timeout: 180000,
        loadingText: '正在生成 PDF…',
        showSuccess: false,
      });
    } finally {
      action(() => { this.exportingPdf = false; })();
    }
  }
}
