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
 * 并发防护（2026-10-26）：保存/完成互斥守卫（进行中重复调用直接忽略，
 * 与 Excel 路线同范式）；保存携带乐观锁令牌 expected_version
 * （详情顶层 version 为基线，缺省不带，后端不校验）。
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
  savedVersion = undefined;       // 乐观锁令牌基线（详情顶层 version；缺省则请求不带）
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
  detailLoadSeq = 0;              // 详情请求序列号（乱序/关闭后旧响应丢弃）

  @action applyDetail(res) {
    const payload = res && res.data ? res.data : res;
    if (!payload) {
      // 返回列表：使在途详情请求失效——否则详情关闭后旧响应落地仍会
      // applyDetail 胜出，把已退出的台账重新打开（与 excelLedgerStore 同口径）
      this.detailLoadSeq += 1;
      this.loading = false;
    }
    this.detail = payload;
    const values = payload && payload.form ? payload.form.values : {};
    this.values = {...(values || {})};
    this.savedValues = {...(values || {})};
    // 乐观锁基线：详情/完成响应统一从顶层 version 更新；旧后端/测试
    // mock 无 version 时置 undefined（保存请求缺省不带令牌）
    this.savedVersion = payload ? payload.version : undefined;
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
    // 竞态守卫（快速连开两条详情/详情关闭后旧响应落地）：发起时取序列号，
    // 响应落地前序列号已被更新（新请求或 applyDetail(null)）则整体丢弃——
    // 旧详情不得覆盖新台账（否则后续保存 PUT 会发往错误台账 id）
    const seq = ++this.detailLoadSeq;
    action(() => { this.loading = true; })();
    try {
      const res = await http.get(`${API}/${ledgerId}/`);
      if (seq !== this.detailLoadSeq) return this.detail;
      this.applyDetail(res);
      return this.detail;
    } finally {
      // 仅最新请求负责复位 loading（被取代的旧请求不复位）；action 包裹：
      // loading 复位必须触发订阅者重渲染（2026-10-17 实机缺陷，与
      // excelLedgerStore 同一竞态防御）
      if (seq === this.detailLoadSeq) {
        action(() => { this.loading = false; })();
      }
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

  /**
   * 填写区可编辑：完成填写在途时锁定——完成成功后以服务端详情整体重置
   * values，在途输入会被静默丢弃（普通保存不重置编辑副本，期间仍可输入）。
   */
  @computed get fillEditable() {
    return this.editable && !this.submitting;
  }

  @computed get formStructure() {
    return (this.detail && this.detail.form && this.detail.form.version.form) || {groups: []};
  }

  /**
   * 保存未保存填写值（内部无并发守卫，供 saveValues/complete 复用）：
   * 携带乐观锁令牌 expected_version（详情顶层 version 为基线，缺省不带）；
   * 成功后只更新详情与保存基线，不重置编辑副本 values（与 Excel 路线
   * 同范式：在途新输入保留，仍如实显示未保存）。
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
    // 保存在途期间返回列表/切换详情：旧响应不写回（与 excelLedgerStore
    // 同口径——刚关闭的台账不得被重新打开，新详情不得被覆盖）
    if (!this.detail || this.detail.id !== ledgerId) return null;
    const values = payload && payload.form ? payload.form.values : this.values;
    action(() => {
      this.savedValues = {...(values || {})};
      this.detail = payload;
      if (payload && payload.version !== undefined && payload.version !== null) {
        this.savedVersion = payload.version;
      }
    })();
    // 保存成功即旧预览过期（PDF 只反映已保存数据）
    this.invalidatePdfPreview();
    if (options.successText) message.success(options.successText);
    return this.detail;
  }

  /** 保存草稿（次操作）：保存未保存的填写值；保存中/提交中重复点击忽略。 */
  async saveValues() {
    if (!this.detail || this.saving || this.submitting) return;
    if (!this.valuesDirty) return;
    this.saving = true;
    try {
      await this._savePendingChanges({successText: '填写内容已保存'});
    } finally {
      action(() => { this.saving = false; })();
    }
  }

  /**
   * 完成填写（主操作，流程终点）：先把未保存内容保存成功（保存失败
   * 不进入完成），后端做必填终验；保存中/完成中重复调用直接忽略，
   * 防止重复点击与并发处理（与 Excel 路线同范式）。
   */
  async complete() {
    if (!this.detail || this.saving || this.submitting) return;
    const ledgerId = this.detail.id;
    this.submitting = true;
    try {
      await this._savePendingChanges({successText: '填写内容已保存'});
      // 保存在途期间返回列表/切换详情：本台账的完成流程终止（与
      // excelLedgerStore 同口径）
      if (!this.detail || this.detail.id !== ledgerId) return;
      const res = await http.post(`${API}/${ledgerId}/complete/`, {source: 'form-detail'});
      // 完成请求在途期间返回列表：响应落地不得把已关闭的详情重新打开
      if (!this.detail || this.detail.id !== ledgerId) return;
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
