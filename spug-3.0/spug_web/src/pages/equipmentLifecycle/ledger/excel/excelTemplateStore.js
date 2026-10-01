/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账模板 Store（2026-09-28 试点；2026-09-29 批量绑定）。
 *
 * 职责边界：
 * - 只对接 /api/equipment-lifecycle/excel-templates 正式试点接口；
 * - 状态：模板列表、当前模板草稿（布局/绑定）、发布版本列表；
 * - 删除：逻辑删除（后端 is_active=False），成功后重取列表，失败由
 *   公共拦截器提示（不重复弹窗）；
 * - 绑定保存失败回退本地并依赖公共拦截器提示（不重复弹错、不吞拒绝）；
 * - field_id 由前端生成 UUID（不经坐标派生），服务端全量校验；
 * - 批量绑定：单选/Ctrl 加选/拖拽矩形多选可绑定单元格后，用同一组字段
 *   属性一次保存；选区限定当前工作表（切换工作表即清空），已绑定与
 *   被阻挡（内容/合并覆盖）单元格不进入选区；
 * - 批量字段命名：多格=「前缀-坐标」按行列排序生成，单格保留前缀原样；
 * - 保存成功后重新拉取详情，以服务端数据为最终状态；
 * - 草稿 PDF 预览：POST preview/pdf/ 取二进制后新窗口打开（弹窗被拦截
 *   时回退下载），错误由公共拦截器统一提示（不重复弹错、不乐观成功）；
 * - 兼容性检查：详情接口返回的草稿/环境检查结果原样透传给页面展示；
 * - PDF 参数（2026-09-30）：模板级参数抽屉配置（草稿布局 JSON 内），
 *   PUT pdf-params/ 整体校验保存，发布随版本快照固定；
 * - default_value/operation_guide/abnormal_rule/maintenance_cycles 已
 *   退役，绑定载荷不再携带（历史数据由服务端原样兼容）。
 */
import {observable, action, computed, toJS} from 'mobx';
import {message} from 'antd';
import {http, exportFile} from 'libs';
import {uuidv4} from './utils';
import {bindBlockReason, parseCoord, coordName} from './components/LayoutTable';
import {normalizePdfParams, serializePdfParams} from './pdfParams';

export const API = '/api/equipment-lifecycle/excel-templates';

/** 坐标按行列升序（预览与保存顺序稳定） */
export function sortCoords(coordinates) {
  return [...coordinates].sort((a, b) => {
    const left = parseCoord(a);
    const right = parseCoord(b);
    return left.row - right.row || left.col - right.col;
  });
}

/** 批量字段命名规则：单格保留前缀原样，多格=「前缀-坐标」 */
export function batchFieldNames(prefix, coordinates) {
  const sorted = sortCoords(coordinates);
  return sorted.map(coord => (sorted.length === 1 ? prefix : `${prefix}-${coord}`));
}

export class ExcelTemplateStore {
  @observable list = [];
  @observable loading = false;
  @observable current = null;       // 当前模板详情（含 draft：layout/field_bindings）
  @observable activeSheet = '';
  @observable selectedCell = '';
  @observable selectedCells = [];   // 批量绑定选区（仅当前工作表内可绑定单元格）
  @observable isDragging = false;   // 拖拽矩形选区进行中
  @observable saving = false;
  @observable uploading = false;
  @observable uploadProgress = 0;
  @observable publishing = false;
  @observable previewing = false;   // 草稿 PDF 预览请求进行中（按钮 loading）
  @observable deletingId = '';      // 正在删除的模板 id（按钮 loading 防重复点击）
  @observable versions = [];
  @observable versionsVisible = false;
  @observable pdfDrawerVisible = false;  // PDF 参数抽屉
  @observable pdfForm = null;            // PDF 参数表单态（null=抽屉未打开）
  @observable savingPdfParams = false;   // PDF 参数保存进行中
  @observable uploadName = '';      // 上传面板：模板名称
  @observable uploadType = undefined; // 上传面板：维护类型
  // 拖拽内部状态（不驱动渲染，不设 observable）
  dragAnchor = '';
  dragMoved = false;

  @computed get draft() {
    return this.current ? this.current.draft : null;
  }

  /** 草稿兼容性检查结果（详情接口返回；无草稿/未返回时为 null）。 */
  @computed get compatibility() {
    return this.current && this.current.compatibility
      ? this.current.compatibility : null;
  }

  /** 模板级 PDF 参数（草稿携带；旧草稿无此键时为空对象）。 */
  @computed get pdfParams() {
    return this.draft ? (this.draft.pdf_params || {}) : {};
  }

  @computed get layout() {
    return this.draft ? this.draft.layout : null;
  }

  @computed get currentSheet() {
    if (!this.layout || !this.layout.sheets || !this.layout.sheets.length) return null;
    return this.layout.sheets.find(s => s.name === this.activeSheet)
      || this.layout.sheets[0] || null;
  }

  @computed get bindings() {
    return this.draft ? (this.draft.field_bindings || []) : [];
  }

  @computed get bindingByCell() {
    const map = {};
    this.bindings.forEach(b => {
      map[`${b.sheet_name}!${b.cell_coordinate}`] = b;
    });
    return map;
  }

  @computed get selectedBinding() {
    return this.bindingByCell[`${this.activeSheet}!${this.selectedCell}`] || null;
  }

  @action applyDetail(detail) {
    // http 拦截器剥一层后仍可能保留 {data:{...}} 外壳（json_response 双层
    // data 包装），统一剥离兼容
    const payload = detail && detail.data ? detail.data : detail;
    this.current = payload;
    this.activeSheet = payload && payload.draft ? (payload.draft.sheet_name || '') : '';
    this.selectedCell = '';
    this.resetSelection();
  }

  @action setUploadField(key, value) {
    this[key] = value;
  }

  async fetchList() {
    this.loading = true;
    try {
      const res = await http.get(`${API}/`);
      const payload = res && res.data ? res.data : res;
      this.list = Array.isArray(payload) ? payload : (payload.templates || []);
    } finally {
      this.loading = false;
    }
  }

  async fetchDetail(templateId) {
    this.loading = true;
    try {
      const res = await http.get(`${API}/${templateId}/`);
      this.applyDetail(res);
      return this.current;
    } finally {
      this.loading = false;
    }
  }

  async upload(fields, file) {
    const formData = new FormData();
    Object.keys(fields || {}).forEach(key => formData.append(key, fields[key] || ''));
    formData.append('file', file);
    this.uploading = true;
    this.uploadProgress = 0;
    try {
      const res = await http.post(`${API}/`, formData, {
        onUploadProgress: event => {
          if (event.total) this.uploadProgress = Math.round(event.loaded / event.total * 100);
        },
      });
      this.applyDetail(res);
      return this.current;
    } finally {
      this.uploading = false;
    }
  }

  async reuploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    this.uploading = true;
    try {
      const res = await http.post(`${API}/${this.current.id}/draft-file/`, formData);
      this.applyDetail(res);
      return this.current;
    } finally {
      this.uploading = false;
    }
  }

  @action selectCell(coordinate) {
    this.selectedCell = this.selectedCell === coordinate ? '' : coordinate;
  }

  @action setSheet(name) {
    this.activeSheet = name;
    this.selectedCell = '';
    // 批量选区限定单工作表：切换即清空，杜绝跨工作表混合批量绑定
    this.resetSelection();
  }

  /** 单元格是否可进入批量选区（未绑定且无内容/合并阻挡） */
  isCellSelectable(coordinate) {
    const sheet = this.currentSheet;
    if (!sheet || !coordinate) return false;
    if (this.bindingByCell[`${this.activeSheet}!${coordinate}`]) return false;
    return !bindBlockReason(sheet, coordinate);
  }

  /** 拖拽矩形内的可绑定单元格（合并覆盖/内容格自动剔除） */
  cellsInRectangle(fromCoord, toCoord) {
    const sheet = this.currentSheet;
    if (!sheet || !fromCoord || !toCoord) return [];
    const from = parseCoord(fromCoord);
    const to = parseCoord(toCoord);
    const rowMin = Math.min(from.row, to.row);
    const rowMax = Math.max(from.row, to.row);
    const colMin = Math.min(from.col, to.col);
    const colMax = Math.max(from.col, to.col);
    const cells = [];
    for (let row = rowMin; row <= rowMax; row++) {
      for (let col = colMin; col <= colMax; col++) {
        const coordinate = coordName(row, col);
        if (this.isCellSelectable(coordinate)) cells.push(coordinate);
      }
    }
    return cells;
  }

  @action beginDrag(coordinate, event) {
    const mouseEvent = event || {};
    if (mouseEvent.button !== undefined && mouseEvent.button !== 0) return;
    if (!this.isCellSelectable(coordinate)) return;
    this.dragAnchor = coordinate;
    this.isDragging = true;
    this.dragMoved = false;
  }

  @action extendDrag(coordinate) {
    if (!this.isDragging) return;
    this.selectedCells = this.cellsInRectangle(this.dragAnchor, coordinate);
    if (coordinate !== this.dragAnchor) this.dragMoved = true;
  }

  @action endDrag() {
    this.isDragging = false;
  }

  @action clearSelection() {
    this.resetSelection();
  }

  @action resetSelection() {
    this.selectedCells = [];
    this.isDragging = false;
    this.dragAnchor = '';
    this.dragMoved = false;
  }

  /** 单元格点击：Ctrl/Cmd 加选批量选区，普通点击走单格绑定面板 */
  @action handleCellClick(coordinate, event) {
    const mouseEvent = event || {};
    if (this.dragMoved) {
      this.dragMoved = false;
      return;
    }
    if (mouseEvent.ctrlKey || mouseEvent.metaKey) {
      if (!this.isCellSelectable(coordinate)) return;
      this.selectedCell = '';
      this.selectedCells = this.selectedCells.includes(coordinate)
        ? this.selectedCells.filter(item => item !== coordinate)
        : [...this.selectedCells, coordinate];
      return;
    }
    this.selectedCells = [];
    this.selectCell(coordinate);
  }

  /** 保存绑定（新建或编辑，field_id 保持稳定），失败回退本地数据。 */
  @action async saveBinding(form) {
    if (!this.current) return;
    const existing = this.selectedBinding;
    const binding = {
      field_id: existing ? existing.field_id : uuidv4(),
      sheet_name: this.activeSheet,
      cell_coordinate: this.selectedCell,
      field_name: form.field_name,
      input_type: form.input_type,
      is_required: !!form.is_required,
      unit: form.unit || '',
      options: form.input_type === 'status' ? ['正常', '异常']
        : (form.input_type === 'choice' ? (form.options || []) : []),
    };
    const previous = this.current;
    const others = this.bindings.filter(
      b => !existing || b.field_id !== existing.field_id);
    this.current = {
      ...this.current,
      draft: {...this.draft, field_bindings: [...others, binding]},
    };
    try {
      await this.persist();
      message.success('绑定已保存');
    } catch (e) {
      this.current = previous;
      throw e;
    }
  }

  /**
   * 批量绑定：为选区内每个单元格生成独立 UUID 的绑定并整体保存。
   * 失败回退本地数据（不显示成功提示）；成功后重新拉取详情，
   * 以服务端返回为最终状态。
   */
  @action async saveBatchBinding(form) {
    if (!this.current || !this.selectedCells.length) return;
    const coords = sortCoords(toJS(this.selectedCells));
    const names = batchFieldNames(form.field_name.trim(), coords);
    const options = form.input_type === 'status' ? ['正常', '异常']
      : (form.input_type === 'choice' ? (form.options || []) : []);
    const additions = coords.map((coordinate, index) => ({
      field_id: uuidv4(),
      sheet_name: this.activeSheet,
      cell_coordinate: coordinate,
      field_name: names[index],
      input_type: form.input_type,
      is_required: !!form.is_required,
      unit: form.unit || '',
      options,
    }));
    const previous = this.current;
    this.current = {
      ...this.current,
      draft: {...this.draft, field_bindings: [...this.bindings, ...additions]},
    };
    try {
      await this.persist();
      await this.fetchDetail(this.current.id);
      this.resetSelection();
      this.selectedCell = '';
      message.success(`已批量绑定 ${additions.length} 个字段`);
    } catch (e) {
      this.current = previous;
      throw e;
    }
  }

  /** 删除绑定（面板 Popconfirm 确认后调用），失败回退。 */
  @action async removeBinding(fieldId) {
    if (!this.current) return;
    const previous = this.current;
    this.current = {
      ...this.current,
      draft: {
        ...this.draft,
        field_bindings: this.bindings.filter(b => b.field_id !== fieldId),
      },
    };
    this.selectedCell = '';
    try {
      await this.persist();
      message.success('绑定已删除');
    } catch (e) {
      this.current = previous;
      throw e;
    }
  }

  /** 绑定整体保存（服务端全量校验后落库）。 */
  async persist() {
    if (!this.current) return;
    this.saving = true;
    try {
      const res = await http.put(`${API}/${this.current.id}/bindings/`,
        {field_bindings: toJS(this.bindings)});
      this.applyDetail(res);
    } finally {
      this.saving = false;
    }
  }

  /** 发布：当前草稿通过发布级校验后快照为新版本（不可变）。 */
  async publish() {
    this.publishing = true;
    try {
      await http.post(`${API}/${this.current.id}/publish/`);
      message.success('发布成功');
      await this.fetchDetail(this.current.id);
    } finally {
      this.publishing = false;
    }
  }

  // ==================== PDF 打印参数（模板级，随版本快照） ====================

  /** 打开参数抽屉：以当前草稿参数预填表单（缺省项补全）。 */
  @action openPdfDrawer() {
    this.pdfForm = normalizePdfParams(toJS(this.pdfParams));
    this.pdfDrawerVisible = true;
  }

  @action closePdfDrawer() {
    this.pdfDrawerVisible = false;
    this.pdfForm = null;
  }

  @action setPdfForm(form) {
    this.pdfForm = form;
  }

  /**
   * 保存 PDF 参数（服务端全量校验后写入草稿布局 JSON）。
   * 本地序列化失败 warning 提示并返回 false；HTTP 失败由公共拦截器
   * 统一提示（不重复弹错），抽屉保持打开。
   */
  @action async savePdfParams() {
    if (!this.current || !this.pdfForm) return false;
    const {payload, error} = serializePdfParams(this.pdfForm);
    if (error) {
      message.warning(error);
      return false;
    }
    this.savingPdfParams = true;
    try {
      const res = await http.put(`${API}/${this.current.id}/pdf-params/`,
        {pdf_params: payload});
      this.applyDetail(res);
      message.success('PDF 参数已保存');
      this.closePdfDrawer();
      return true;
    } finally {
      this.savingPdfParams = false;
    }
  }

  /**
   * 删除模板（逻辑删除/停用，幂等）：成功提示后重取列表（不做乐观删除）。
   * 失败由公共拦截器统一提示业务错误，这里不再重复弹窗，只向上传递拒绝。
   */
  async deleteTemplate(templateId) {
    this.deletingId = templateId;
    try {
      await http.delete(`${API}/${templateId}/`);
      message.success('模板已删除');
      await this.fetchList();
    } finally {
      this.deletingId = '';
    }
  }

  /**
   * 草稿 PDF 预览：请求二进制后新窗口打开（弹窗被拦截时回退下载）。
   * 失败由公共拦截器统一提示业务错误（如 LibreOffice 不可用），
   * 这里不重复弹错、不做乐观成功提示；只读接口可重复调用。
   */
  async previewPdf() {
    if (!this.current || !this.draft) return;
    this.previewing = true;
    try {
      const response = await http.post(
        `${API}/${this.current.id}/preview/pdf/`, null,
        {responseType: 'arraybuffer', timeout: 180000});
      this.openPdfResponse(response);
    } finally {
      this.previewing = false;
    }
  }

  /** 二进制响应 → Blob 新窗口打开；window.open 返回空（被拦截）则回退下载。 */
  openPdfResponse(response) {
    const bytes = response && response.data;
    if (!bytes || !bytes.byteLength) return;
    const contentType = (response.headers
      && (response.headers['content-type'] || response.headers['Content-Type']))
      || 'application/pdf';
    const blob = new Blob([bytes], {type: contentType});
    const url = window.URL.createObjectURL(blob);
    const win = window.open(url, '_blank');
    if (!win) this.downloadPdfBlob(blob, url);
    // 留足新窗口加载时间再释放对象 URL，避免预览窗口空白
    setTimeout(() => window.URL.revokeObjectURL(url), 60000);
  }

  /** 下载回退（浏览器拦截弹窗/不支持新窗口时）。 */
  downloadPdfBlob(blob, url) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(this.current && this.current.name) || '模板'}-模板预览.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  async fetchVersions() {
    const res = await http.get(`${API}/${this.current.id}/versions/`);
    const payload = res && res.data ? res.data : res;
    this.versions = Array.isArray(payload) ? payload : [];
  }

  downloadSample() {
    return exportFile({
      url: `${API}/sample/`,
      method: 'get',
      defaultFilename: '信道维护台账验收样例.xlsx',
    });
  }
}

export default new ExcelTemplateStore();
