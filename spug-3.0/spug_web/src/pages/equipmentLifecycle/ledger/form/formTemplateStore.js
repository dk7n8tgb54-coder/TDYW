/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单台账模板管理 Store（2026-10-21，与 excelTemplateStore 同构精简版）。
 *
 * 状态：模板列表、当前详情（含草稿表单）、创建弹窗、编辑抽屉、版本抽屉。
 * 编辑器打开（openEditor）：列表行只有摘要（无 draft），统一按模板 id
 * 拉取完整详情后才进入编辑；加载中/加载失败/无草稿三态分离，失败时
 * 界面禁止保存与发布；请求带序号竞态防护，旧响应不覆盖新模板。
 * 草稿编辑（编辑器组件内本地 state，保存时整体提交）：
 * - saveDraftForm PUT /form-templates/<pk>/（后端全量校验，未知结构拒绝）；
 * - publish POST /form-templates/<pk>/publish/（发布为不可变版本）；
 * - 配置（适用系统/生成周期）复用 Excel 同构语义（generation-config）。
 * 载入示例：GET /form-templates/sample/（内置示例覆盖全部分组种类）。
 */
import {observable, action} from 'mobx';
import {message} from 'antd';
import {http} from 'libs';

export const API = '/api/equipment-lifecycle/form-templates';

// 后端业务错误统一 HTTP 200 + error，由 http 拦截器弹出并 reject，
// 调用方 catch 后不重复提示。
export class FormTemplateStore {
  @observable list = [];
  @observable isFetching = false;
  @observable detail = null;          // 当前模板详情（含 draft/draft_state）
  @observable versions = [];
  @observable createVisible = false;
  @observable createOptions = null;   // {systems, periods}
  @observable creating = false;
  @observable editorVisible = false;
  @observable editorTemplate = null;  // 编辑中的模板详情（含完整草稿）
  @observable editorLoading = false;  // 编辑器草稿加载中
  @observable editorLoadError = '';   // 编辑器草稿加载失败信息（空=正常）
  // 编辑器详情请求序号：快速切换/关闭模板时使在途请求失效（竞态防护）
  editorLoadSeq = 0;
  @observable savingDraft = false;
  @observable publishing = false;
  @observable versionsVisible = false;
  @observable versionsTemplate = null;
  @observable versionDetail = null;   // 版本内容查看（含 form）
  @observable keyword = '';
  @observable ledgerTypeFilter = '';
  // 模板样张 PDF 预览（2026-10-22）：当前草稿结构的空白样例
  @observable samplePdfUrl = '';      // blob 对象 URL（弹窗 iframe 展示）
  @observable samplePdfMeta = null;   // {pages, paper}（X-El-Pdf-* 反馈头）
  @observable samplePdfLoading = false;
  @observable samplePdfError = '';

  @action setKeyword(value) {
    this.keyword = value;
    return this.fetchList();
  }

  @action setLedgerTypeFilter(value) {
    this.ledgerTypeFilter = value;
    return this.fetchList();
  }

  async fetchList() {
    this.isFetching = true;
    try {
      const res = await http.get(`${API}/`);
      const payload = res && res.data ? res.data : res;
      let rows = Array.isArray(payload) ? payload : [];
      if (this.keyword) {
        const kw = this.keyword.trim().toLowerCase();
        rows = rows.filter(t => (t.name || '').toLowerCase().includes(kw));
      }
      if (this.ledgerTypeFilter) {
        rows = rows.filter(t => t.ledger_type === this.ledgerTypeFilter);
      }
      this.list = rows;
    } finally {
      action(() => { this.isFetching = false; })();
    }
  }

  async fetchDetail(id) {
    const res = await http.get(`${API}/${id}/`);
    const payload = res && res.data ? res.data : res;
    this.detail = payload;
    return payload;
  }

  @action openCreateModal() {
    this.createVisible = true;
    this.fetchCreateOptions().catch(() => {});
  }

  async fetchCreateOptions() {
    const res = await http.get(`${API}/create-options/`);
    const payload = res && res.data ? res.data : res;
    this.createOptions = payload;
    return payload;
  }

  @action closeCreateModal() {
    this.createVisible = false;
  }

  async submitCreate(form) {
    this.creating = true;
    try {
      const res = await http.post(`${API}/`, form);
      const payload = res && res.data ? res.data : res;
      this.createVisible = false;
      message.success('模板已创建，请编辑表单后发布');
      await this.fetchList();
      this.openEditor(payload);
      return payload;
    } finally {
      action(() => { this.creating = false; })();
    }
  }

  @action openEditor(template) {
    // 使任何在途详情请求失效（快速切换模板时旧响应不得覆盖新模板）
    this.editorLoadSeq += 1;
    this.editorTemplate = template;
    this.editorVisible = true;
    this.editorLoadError = '';
    // 创建接口返回的已是完整详情（含 draft/draft_state）；模板列表行是
    // 摘要（无 draft），必须按 id 拉取完整详情后才能进入编辑，否则会把
    // 已保存草稿误显示为空白表单。
    if (template && template.draft_state !== undefined) {
      this.editorLoading = false;
      return;
    }
    this.editorLoading = true;
    this.loadEditorDetail(template && template.id);
  }

  /** 按 id 拉取模板完整详情（含草稿表单）供编辑器使用。 */
  async loadEditorDetail(id) {
    if (!id) return;
    const seq = ++this.editorLoadSeq;
    this.editorLoading = true;
    try {
      const res = await http.get(`${API}/${id}/`);
      const payload = res && res.data ? res.data : res;
      // 竞态防护：编辑器已关闭、请求已被更新的打开动作取代、或当前
      // 编辑对象已不是本模板时，丢弃本次响应
      if (!this.editorVisible || seq !== this.editorLoadSeq) return;
      if (!this.editorTemplate || this.editorTemplate.id !== id) return;
      action(() => {
        this.editorTemplate = payload;
        this.editorLoading = false;
        this.editorLoadError = '';
      })();
    } catch (e) {
      if (!this.editorVisible || seq !== this.editorLoadSeq) return;
      if (!this.editorTemplate || this.editorTemplate.id !== id) return;
      // http 拦截器已弹过错误提示，这里只记录状态供界面展示，不重复提示
      action(() => {
        this.editorLoading = false;
        this.editorLoadError = (typeof e === 'string' && e) || '模板草稿加载失败';
      })();
    }
  }

  @action retryLoadEditor() {
    if (!this.editorTemplate) return;
    this.loadEditorDetail(this.editorTemplate.id);
  }

  @action closeEditor() {
    this.editorLoadSeq += 1;
    this.editorVisible = false;
    this.editorTemplate = null;
    this.editorLoading = false;
    this.editorLoadError = '';
  }

  /**
   * 保存草稿表单（整体提交，后端全量校验）。
   * PUT 成功即视为保存成功并立即返回：列表刷新不阻塞保存结果（失败静默——
   * 拦截器已提示、慢响应不拖住保存 Promise 与编辑器基线更新），列表展示
   * 问题不把已保存内容判成未保存。
   */
  async saveDraftForm(templateId, form) {
    this.savingDraft = true;
    try {
      const res = await http.put(`${API}/${templateId}/`, {form});
      const payload = res && res.data ? res.data : res;
      this.editorTemplate = payload;
      this.detail = payload;
      message.success('草稿已保存');
      this.fetchList().catch(() => {});
      return payload;
    } finally {
      action(() => { this.savingDraft = false; })();
    }
  }

  /**
   * 发布检查（无状态预检提示，2026-10-23 P2）：携带编辑器当前内容
   * （可为未保存草稿）请求结构化 errors/warnings；后端不落库、发布时
   * 仍会行锁内重新全量校验，本结果仅供弹窗展示与点击定位。
   */
  async publishCheck(templateId, form) {
    const res = await http.post(`${API}/${templateId}/publish-check/`, {form});
    const payload = res && res.data ? res.data : res;
    return {
      errors: (payload && payload.errors) || [],
      warnings: (payload && payload.warnings) || [],
    };
  }

  /**
   * 发布（发布的是已保存草稿的快照，后端行锁内重新校验）。
   * POST 成功即发布成功：成功提示对应真实发布结果；随后的详情/列表刷新
   * 失败单独消化（拦截器已提示），不使整个发布 Promise 判败——调用方的
   * catch 不再把已成功的发布当失败处理。
   */
  async publish(templateId) {
    this.publishing = true;
    try {
      await http.post(`${API}/${templateId}/publish/`);
      message.success('已发布新版本');
      const detail = await this.fetchDetail(templateId).catch(() => null);
      if (detail && this.editorVisible) this.editorTemplate = detail;
      await this.fetchList().catch(() => {});
      return detail;
    } finally {
      action(() => { this.publishing = false; })();
    }
  }

  async saveGenerationConfig(templateId, body) {
    const res = await http.put(`${API}/${templateId}/generation-config/`, body);
    const payload = res && res.data ? res.data : res;
    if (this.editorTemplate && this.editorTemplate.id === templateId) {
      this.editorTemplate = payload;
    }
    await this.fetchList();
    return payload;
  }

  async loadSample() {
    const res = await http.get(`${API}/sample/`);
    const payload = res && res.data ? res.data : res;
    return payload;
  }

  @action openVersions(template) {
    this.versionsTemplate = template;
    this.versionsVisible = true;
    this.versionDetail = null;
    http.get(`${API}/${template.id}/versions/`).then(res => {
      const payload = res && res.data ? res.data : res;
      this.versions = Array.isArray(payload) ? payload : [];
    }).catch(() => {});
  }

  @action closeVersions() {
    this.versionsVisible = false;
    this.versionsTemplate = null;
    this.versions = [];
    this.versionDetail = null;
  }

  async fetchVersionDetail(templateId, versionNo) {
    const res = await http.get(`${API}/${templateId}/versions/${versionNo}/`);
    const payload = res && res.data ? res.data : res;
    this.versionDetail = payload;
    return payload;
  }

  async deactivate(id) {
    await http.post(`${API}/${id}/deactivate/`);
    message.success('模板已停用');
    await this.fetchList();
  }

  async activate(id) {
    await http.post(`${API}/${id}/activate/`);
    message.success('模板已启用');
    await this.fetchList();
  }

  async destroy(id) {
    await http.delete(`${API}/${id}/`);
    message.success('模板已删除');
    await this.fetchList();
  }

  // —— 模板样张 PDF 预览（2026-10-22，与台账 PDF 同一套后端版式） ——

  _revokeSamplePdfUrl() {
    if (this.samplePdfUrl) {
      window.URL.revokeObjectURL(this.samplePdfUrl);
      this.samplePdfUrl = '';
    }
  }

  /** 关闭/重置样张预览（blob URL 释放防泄漏）。 */
  @action closeSamplePdf() {
    this._revokeSamplePdfUrl();
    this.samplePdfMeta = null;
    this.samplePdfError = '';
    this.samplePdfLoading = false;
  }

  /**
   * 拉取模板样张 PDF（POST preview/pdf/，arraybuffer）：使用当前已保存
   * 草稿结构生成空白样例（未保存修改由编辑器确认弹窗明确提示）。成功
   * 返回 blob URL 并记录 X-El-Pdf-Pages/Paper 反馈头；失败向上抛出
   * （公共拦截器已提示业务错误），弹窗显示失败态可重试。
   */
  async fetchSamplePdf(templateId) {
    if (!templateId || this.samplePdfLoading) return '';
    action(() => {
      this.samplePdfLoading = true;
      this.samplePdfError = '';
    })();
    try {
      const response = await http.post(
        `${API}/${templateId}/preview/pdf/`, {},
        {responseType: 'arraybuffer', timeout: 180000});
      const bytes = response && response.data;
      if (!bytes || !bytes.byteLength) {
        throw new Error('样张内容为空');
      }
      const headers = (response && response.headers) || {};
      const meta = {
        pages: headers['x-el-pdf-pages'] || '',
        paper: headers['x-el-pdf-paper'] || '',
      };
      const blob = new Blob([bytes], {type: 'application/pdf'});
      const url = window.URL.createObjectURL(blob);
      this._revokeSamplePdfUrl();
      return action(() => {
        this.samplePdfUrl = url;
        this.samplePdfMeta = meta;
        return url;
      })();
    } catch (e) {
      action(() => {
        this.samplePdfError = '样张生成失败，可点击「重新生成」重试';
      })();
      throw e;
    } finally {
      action(() => { this.samplePdfLoading = false; })();
    }
  }
}

export const formTemplateStore = new FormTemplateStore();
