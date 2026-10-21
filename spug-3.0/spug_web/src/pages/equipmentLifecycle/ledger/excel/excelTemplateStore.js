/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 上传版维护台账模板 Store（2026-09-28 试点；2026-09-29 批量绑定）。
 *
 * 职责边界：
 * - 只对接 /api/equipment-lifecycle/excel-templates 正式试点接口；
 * - 状态：模板列表、当前模板草稿（布局/绑定）、发布版本列表；
 * - 删除：物理删除（后端删除时重新检查引用关系），停用=逻辑停用
 *   （2026-10-16 拆分），成功后重取列表，失败由公共拦截器提示（不重复弹窗）；
 * - 绑定保存失败回退本地并依赖公共拦截器提示（不重复弹错、不吞拒绝）；
 * - field_id 由前端生成 UUID（不经坐标派生），服务端全量校验；
 * - 批量绑定：单选/Ctrl 加选/拖拽矩形多选可填写单元格后，用同一组字段
 *   属性一次保存；选区限定当前工作表（切换工作表即清空），已绑定与
 *   未绑定格可混合进入选区（2026-10-19），表头内容格与合并内部格仍排除；
 * - 混合批量保存（2026-10-19）：已绑定格保留 field_id 与自定义名称，
 *   仅更新面板明确修改过的属性（touched 标记）；未绑定格新建绑定并按
 *   规则自动命名；批量解绑为独立操作（面板确认后调用）；
 * - 批量字段命名：多格=「前缀-坐标」按行列排序生成，单格保留前缀原样；
 * - 保存成功后重新拉取详情，以服务端数据为最终状态；
 * - 草稿 PDF 预览：POST preview/pdf/ 取二进制后新窗口打开（弹窗被拦截
 *   时回退下载），错误由公共拦截器统一提示（不重复弹错、不乐观成功）；
 * - 预览反馈（2026-10-19）：响应头携带真实页数/纸张尺寸/版式预检提示
 *   （parsePdfMetaHeaders 解析），previewInfo 标注参数来源（已保存参数/
 *   当前未保存参数）；previewWithFormParams 以表单当前值（含未保存
 *   修改）+ 临时样例数据预览，全部只作用于本次预览副本，不写草稿；
 * - 兼容性检查：详情接口返回的草稿/环境检查结果原样透传给页面展示；
 * - PDF 参数（2026-09-30）：模板级参数抽屉配置（草稿布局 JSON 内），
 *   PUT pdf-params/ 整体校验保存，发布随版本快照固定；
 * - 替换源文件（2026-10-14 交互改造）：选定文件先进入确认弹窗（提示将
 *   清空的绑定数），确认后才调用 draft-file/；取消不产生任何请求；
 * - 新建模板流程（2026-10-21 配置前置）：名称/台账类型/适用系统/生成
 *   周期/源文件集中在弹窗内一次完成；选定文件只登记不上传，「创建并
 *   进入模板编辑」统一缺项校验后一次提交（适用系统与生成周期随创建
 *   同请求保存，后端独立校验），成功才提示并进入绑定工作区，失败弹窗
 *   保持打开可修正重试（下载样例随流程内提供）；
 * - 生成配置（2026-10-14）：适用系统（一模板一系统）+ 生成周期
 *   （按台账类型收敛）经 generation-config 接口保存；空值显式清空回
 *   "待配置"（历史模板不自动推断），只影响自动生成，不影响手工创建；
 *   配置目标默认当前模板详情，也支持列表行级补全（openConfigModal
 *   传入列表行，2026-10-21 待配置模板列表直接补全）；
 * - 版本记录支持列表页按行查看（fetchVersions 按 templateId 取数，
 *   不影响当前模板详情），抽屉标题标注归属模板；
 * - 模板列表双视图（2026-10-19）：在用/已停用按 is_active 拆分，默认
 *   在用；两视图共用关键词（名称/说明/适用系统）与维护类型过滤及
 *   分页，视图数量为各自 is_active 口径的准确总数；
 * - 重新启用（2026-10-19）：停用的逆操作（幂等），成功后重取列表，
 *   模板回到在用视图并恢复用于新台账与自动生成；
 * - 字段名称自动生成（2026-10-19）：新绑定默认「工作表 · 坐标」、
 *   批量每格各生成一个，前缀/名称改为可选；留空保存时回退默认名，
 *   已有自定义名称保持不变，载荷 field_name 始终非空；
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

/** 模板列表每页条数（在用/已停用两视图共用分页规格）。 */
export const LIST_PAGE_SIZE = 10;

/** 坐标按行列升序（预览与保存顺序稳定） */
export function sortCoords(coordinates) {
  return [...coordinates].sort((a, b) => {
    const left = parseCoord(a);
    const right = parseCoord(b);
    return left.row - right.row || left.col - right.col;
  });
}

/**
 * 预览反馈响应头解析（后端由真实生成的 PDF 读取，解析失败不阻断）：
 * X-El-Pdf-Pages（页数）/X-El-Pdf-Paper（如 "A4 210x297mm"）/
 * X-El-Pdf-Warnings（percent 编码 JSON 数组，版式预检提示）。
 */
export function parsePdfMetaHeaders(response) {
  const headers = (response && response.headers) || {};
  const pagesRaw = headers['x-el-pdf-pages'];
  const pages = pagesRaw ? parseInt(pagesRaw, 10) : null;
  let warnings = [];
  try {
    const raw = headers['x-el-pdf-warnings'];
    if (raw) warnings = JSON.parse(decodeURIComponent(raw));
  } catch (e) {
    warnings = [];
  }
  if (!Array.isArray(warnings)) warnings = [];
  return {
    pages: Number.isInteger(pages) && pages > 0 ? pages : null,
    paper: headers['x-el-pdf-paper'] || '',
    warnings,
  };
}

/** 纸张反馈文本格式化："A4 210x297mm" → "A4（210×297 mm）"，原样兜底。 */
export function formatPaperText(paper) {
  const match = /^(?:([A-Za-z0-9]+) )?(\d+)x(\d+)mm$/.exec(paper || '');
  if (!match) return paper || '';
  const [, label, width, height] = match;
  return label ? `${label}（${width}×${height} mm）` : `${width}×${height} mm`;
}

/**
 * 绑定字段默认名（2026-10-19 起新绑定不再要求手输名称）：
 * 「工作表名 · 坐标」，如「信道维护记录 · C4」；无工作表名时退为坐标。
 */
export function defaultFieldName(sheetName, coordinate) {
  return sheetName ? `${sheetName} · ${coordinate}` : coordinate;
}

/**
 * 批量字段命名规则（2026-10-19 起前缀可选）：
 * 填写前缀 → 单格保留前缀、多格「前缀-坐标」（历史行为不变）；
 * 留空 → 每格默认名「工作表名 · 坐标」。
 */
export function batchFieldNames(prefix, coordinates, sheetName) {
  const sorted = sortCoords(coordinates);
  const trimmed = (prefix || '').trim();
  if (!trimmed) return sorted.map(coord => defaultFieldName(sheetName, coord));
  return sorted.map(coord => (sorted.length === 1 ? trimmed : `${trimmed}-${coord}`));
}

export class ExcelTemplateStore {
  @observable list = [];
  @observable loading = false;
  // 模板列表双视图状态（2026-10-19）：默认在用；切换/过滤时分页回到第 1 页
  @observable listView = 'active';  // 'active' 在用 | 'disabled' 已停用
  @observable listKeyword = '';     // 关键词（名称/说明/适用系统）
  @observable listType = '';        // 维护类型筛选（空=全部）
  @observable listPage = 1;
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
  @observable versionsOwner = '';        // 版本抽屉归属模板名（列表行/工作区共用）
  @observable createVisible = false;     // 新建模板弹窗（列表页主操作流程）
  @observable reuploadConfirmVisible = false; // 替换源文件确认弹窗
  @observable pdfDrawerVisible = false;  // PDF 参数抽屉
  @observable pdfForm = null;            // PDF 参数表单态（null=抽屉未打开）
  @observable savingPdfParams = false;   // PDF 参数保存进行中
  @observable sampleForm = {};           // 临时预览数据（field_id → 值，仅本次预览）
  @observable previewInfo = null;        // 最近一次预览反馈（页数/纸张/提示/参数来源）
  @observable uploadName = '';      // 上传面板：模板名称
  @observable uploadType = undefined; // 上传面板：维护类型
  // 新建模板流程（2026-10-21 配置前置）：适用系统/生成周期/源文件与
  // 表单缺项提示；选定文件只登记不立即上传，「创建并进入模板编辑」
  // 统一校验后一次提交（成功才提示并进入工作区，失败弹窗保持可重试）
  @observable uploadSystem = undefined;   // 新建流程：适用系统 id
  @observable uploadPeriod = '';          // 新建流程：生成周期
  @observable createOptions = {systems: [], periods: {}}; // 新建表单选项
  @observable createErrors = {};          // 新建表单缺项提示（字段 → 文案）
  @observable uploadFileName = '';        // 新建流程：已选源文件名（展示）
  // 生成配置弹窗（适用系统 + 生成周期，2026-10-14 本期应填台账生成）
  @observable configVisible = false;
  @observable configSaving = false;
  @observable configSystem = undefined;   // 表单态：适用系统 id
  @observable configPeriod = '';          // 表单态：生成周期
  @observable configSystems = [];         // 可选系统（后端专用接口返回）
  @observable configPeriodOptions = [];   // 按台账类型收敛的周期候选
  @observable configTemplateId = null;    // 配置目标模板（工作区当前或列表行）
  @observable configTemplateName = '';    // 行级补全时弹窗标题标注归属
  @observable configLedgerType = '';      // 目标模板类型（周期候选收敛用）
  // 模板编辑页内打印预览（2026-10-21 统一观感）：iframe 展示与导出同一
  // 生成服务的真实 PDF；草稿在预览后再变更时标记过期提示刷新
  @observable printPreviewUrl = '';       // blob 对象 URL（iframe 展示）
  @observable printPreviewMeta = null;    // {pages, paper, source}（反馈头）
  @observable printPreviewLoading = false;
  @observable printPreviewError = '';
  @observable printPreviewStale = false;  // 预览生成后草稿又有变更
  // 拖拽内部状态（不驱动渲染，不设 observable）
  dragAnchor = '';
  dragMoved = false;
  // 待确认替换的源文件（弹窗确认前不发起请求，不驱动渲染）
  pendingReuploadFile = null;
  // 新建流程待提交源文件（File 对象不进 observable，提交前不发起请求）
  pendingCreateFile = null;

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

  /**
   * 打印设置表单是否有未保存修改（与草稿已保存参数序列化对比）：
   * 用于区分「预览空白打印稿」（已保存参数）与「应用当前设置并预览」
   * （表单当前值）两个入口的参数来源。
   */
  @computed get pdfFormDirty() {
    if (!this.pdfForm) return false;
    const current = serializePdfParams(this.pdfForm);
    if (current.error) return true;
    const saved = serializePdfParams(normalizePdfParams(toJS(this.pdfParams)));
    return JSON.stringify(current.payload) !== JSON.stringify(saved.payload);
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
    // 返回列表清掉页内预览（blob URL 释放）；保存/刷新详情后已有预览
    // 标记过期（草稿已变更，预览需手动刷新，不静默当作最新版式）
    if (!payload) {
      this.resetPrintPreview();
    } else if (this.printPreviewUrl) {
      this.printPreviewStale = true;
    }
  }

  @action setUploadField(key, value) {
    this[key] = value;
  }

  // ==================== 模板列表双视图（在用/已停用，2026-10-19） ====================

  /** 在用视图数据源：按 is_active 拆分后再套用关键词与类型过滤。 */
  @computed get activeTemplates() {
    return this._filterRows(this.list.filter(t => t.is_active));
  }

  /** 已停用视图数据源。 */
  @computed get disabledTemplates() {
    return this._filterRows(this.list.filter(t => !t.is_active));
  }

  /** 视图数量：只按启用状态统计的准确总数（不受关键词/类型过滤影响）。 */
  @computed get activeCount() {
    return this.list.filter(t => t.is_active).length;
  }

  @computed get disabledCount() {
    return this.list.filter(t => !t.is_active).length;
  }

  /** 视图内过滤：维护类型 + 关键词（名称/说明/适用系统，大小写不敏感）。 */
  _filterRows(rows) {
    const keyword = this.listKeyword.trim().toLowerCase();
    return rows.filter(row => {
      if (this.listType && row.ledger_type !== this.listType) return false;
      if (!keyword) return true;
      const haystack = [
        row.name, row.description, row.system_name, row.system_code,
      ].join(' ').toLowerCase();
      return haystack.includes(keyword);
    });
  }

  @action setListView(view) {
    if (this.listView === view) return;
    this.listView = view === 'disabled' ? 'disabled' : 'active';
    this.listPage = 1;
  }

  @action setListFilter(key, value) {
    this[key] = value;
    if (key !== 'listPage') this.listPage = 1;
  }

  // ==================== 生成配置（适用系统 + 生成周期，2026-10-14） ====================

  /** 打开配置弹窗：拉取当前配置与选项（系统清单/周期候选），失败由公共拦截器提示。
   * record 缺省为当前模板详情（工作区「配置」入口）；传入列表行时为
   * 行级补全入口（2026-10-21 待配置模板在列表直接补全，不进工作区）。 */
  @action async openConfigModal(record) {
    const target = record || this.current;
    if (!target) return;
    this.configVisible = true;
    this.configTemplateId = target.id;
    this.configTemplateName = target.name || '';
    this.configLedgerType = target.ledger_type || '';
    this.configSystem = target.system || undefined;
    this.configPeriod = target.generation_period || '';
    this.configSystems = [];
    this.configPeriodOptions = [];
    const res = await http.get(`${API}/${target.id}/generation-config/`);
    const payload = res && res.data ? res.data : res;
    this.configSystems = (payload && payload.systems) || [];
    const periods = (payload && payload.periods) || {};
    this.configPeriodOptions = periods[this.configLedgerType] || [];
  }

  @action closeConfigModal() {
    this.configVisible = false;
  }

  @action setConfigField(key, value) {
    this[key] = value;
  }

  /**
   * 保存生成配置（整体校验后落库）；空值显式清空回"待配置"。
   * 成功后重取列表；目标是当前模板时同步刷新详情以服务端数据为准。
   */
  @action async saveGenerationConfig() {
    if (!this.configTemplateId) return;
    this.configSaving = true;
    try {
      const res = await http.put(`${API}/${this.configTemplateId}/generation-config/`, {
        system: this.configSystem || '',
        generation_period: this.configPeriod || '',
      });
      if (this.current && this.current.id === this.configTemplateId) {
        this.applyDetail(res);
      }
      this.configVisible = false;
      message.success('生成配置已保存');
      await this.fetchList();
      return this.current;
    } finally {
      this.configSaving = false;
    }
  }

  // ==================== 新建模板流程（2026-10-21 配置前置） ====================

  /** 新建表单周期候选：按所选台账类型收敛（周月=每周/每月，季=每航季）。 */
  @computed get createPeriodOptions() {
    return this.createOptions.periods[this.uploadType] || [];
  }

  @action openCreateModal() {
    this.createVisible = true;
    this.createErrors = {};
    // 选项（系统清单/周期候选）随弹窗拉取，失败由公共拦截器提示，
    // 弹窗保持打开可重试（关闭再打开会重新拉取）
    http.get(`${API}/create-options/`).then(res => {
      const payload = res && res.data ? res.data : res;
      this.createOptions = {
        systems: (payload && payload.systems) || [],
        periods: (payload && payload.periods) || {},
      };
    }).catch(() => {});
  }

  @action closeCreateModal() {
    this.createVisible = false;
  }

  /**
   * 设置新建表单字段；切换台账类型时按类型收敛生成周期（季维护自动
   * 设为每航季并明确显示；周月维护保留每周/每月、清除不兼容的周期值），
   * 并清除该字段已有的缺项提示。
   */
  @action setUploadField(key, value) {
    this[key] = value;
    if (key === 'uploadType') {
      if (value === 'seasonal') {
        this.uploadPeriod = 'seasonal';
      } else if (this.uploadPeriod && this.uploadPeriod !== 'weekly'
                 && this.uploadPeriod !== 'monthly') {
        this.uploadPeriod = '';
      }
    }
    if (this.createErrors[key]) {
      const next = {...this.createErrors};
      delete next[key];
      this.createErrors = next;
    }
  }

  /** 新建流程选定源文件：只登记（校验扩展名），不发起任何上传请求。 */
  @action pickCreateFile(file) {
    if (!/\.xlsx$/i.test(file.name)) {
      message.error('仅支持 .xlsx 文件（暂不支持 .xls 与 WPS 私有格式）');
      return false;
    }
    this.pendingCreateFile = file;
    this.uploadFileName = file.name;
    if (this.createErrors.file) {
      const next = {...this.createErrors};
      delete next.file;
      this.createErrors = next;
    }
    return false;
  }

  /** 移除已选源文件（回退为未选择状态，不产生请求）。 */
  @action removeCreateFile() {
    this.pendingCreateFile = null;
    this.uploadFileName = '';
  }

  /** 新建表单缺项校验：名称/类型/适用系统/生成周期/文件逐项给出提示。 */
  @action validateCreateForm() {
    const errors = {};
    if (!(this.uploadName || '').trim()) errors.name = '请填写模板名称';
    if (!this.uploadType) errors.uploadType = '请选择台账类型';
    if (!this.uploadSystem) errors.uploadSystem = '请选择适用系统';
    if (!this.uploadPeriod) errors.uploadPeriod = '请选择生成周期';
    if (!this.pendingCreateFile) errors.file = '请选择 .xlsx 模板文件';
    this.createErrors = errors;
    return !Object.keys(errors).length;
  }

  /** 成功创建后清空新建表单（含已登记文件），弹窗由页面关闭。 */
  @action resetCreateForm() {
    this.uploadName = '';
    this.uploadType = undefined;
    this.uploadSystem = undefined;
    this.uploadPeriod = '';
    this.uploadFileName = '';
    this.pendingCreateFile = null;
    this.createErrors = {};
  }

  /**
   * 创建并进入模板编辑（统一校验后一次提交）：名称/类型/适用系统/
   * 生成周期/文件全部就绪才发请求（缺项只提示不发请求）；提交中重复
   * 调用忽略（防重复提交）；失败向上抛出（公共拦截器已提示），弹窗
   * 保持打开可修正重试——绝不出现"保存失败却提示创建完成"。
   */
  @action async submitCreate() {
    if (this.uploading) return null;
    if (!this.validateCreateForm()) return null;
    const fields = {
      name: this.uploadName,
      ledger_type: this.uploadType,
      system: this.uploadSystem || '',
      generation_period: this.uploadPeriod || '',
    };
    const detail = await this.upload(fields, this.pendingCreateFile);
    this.resetCreateForm();
    return detail;
  }

  /** 选定待替换文件：只登记并弹确认框，不发起任何请求。 */
  @action requestReupload(file) {
    this.pendingReuploadFile = file;
    this.reuploadConfirmVisible = true;
  }

  @action cancelReupload() {
    this.reuploadConfirmVisible = false;
    this.pendingReuploadFile = null;
  }

  /**
   * 确认替换源文件：此时才真正上传。返回 promise 供 Modal onOk 使用
   * （失败时弹窗保持打开，错误由公共拦截器提示）。
   */
  @action async confirmReupload() {
    const file = this.pendingReuploadFile;
    if (!this.current || !file) return;
    this.reuploadConfirmVisible = false;
    this.pendingReuploadFile = null;
    await this.reuploadFile(file);
    message.success('源文件已替换，原绑定已清空，请重新绑定');
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

  /**
   * 单元格是否可进入批量选区（2026-10-19 起已绑定格也可进入，支持
   * 已绑定+未绑定混合选区）：仍排除表头/有内容格与合并区域内部格。
   */
  isCellSelectable(coordinate) {
    const sheet = this.currentSheet;
    if (!sheet || !coordinate) return false;
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

  /**
   * 保存绑定（新建或编辑，field_id 保持稳定），失败回退本地数据。
   * 字段名留空（含纯空白）时回退默认名「工作表 · 坐标」，保证载荷
   * field_name 非空（后端仍为非空校验权威）；自定义名称原样保留。
   */
  @action async saveBinding(form) {
    if (!this.current) return;
    const existing = this.selectedBinding;
    const binding = {
      field_id: existing ? existing.field_id : uuidv4(),
      sheet_name: this.activeSheet,
      cell_coordinate: this.selectedCell,
      field_name: (form.field_name || '').trim()
        ? form.field_name : defaultFieldName(this.activeSheet, this.selectedCell),
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
   * 批量保存（2026-10-19 混合选区：已绑定+未绑定格可同选区）：
   * - 未绑定格新建绑定，名称按现有规则自动生成（前缀可选，batchFieldNames
   *   兜底）；
   * - 已绑定格保留 field_id 与自定义字段名称，仅更新面板明确修改过的属性
   *   （form.touched 标记：input_type/is_required/unit/options），未触碰
   *   属性原样保留；
   * - 失败回退本地数据（不显示成功提示）；成功后重新拉取详情，
   *   以服务端返回为最终状态。
   */
  @action async saveBatchBinding(form) {
    if (!this.current || !this.selectedCells.length) return;
    const coords = sortCoords(toJS(this.selectedCells));
    const touched = form.touched || {};
    const canonicalOptions = form.input_type === 'status' ? ['正常', '异常']
      : (form.input_type === 'choice' ? (form.options || []) : []);
    const coordSet = new Set(coords);
    const anyTouched = ['input_type', 'is_required', 'unit', 'options']
      .some(key => touched[key]);
    const nextBindings = [];
    let updatedCount = 0;
    this.bindings.forEach(binding => {
      const inSelection = binding.sheet_name === this.activeSheet
        && coordSet.has(binding.cell_coordinate);
      if (!inSelection) {
        nextBindings.push(binding);
        return;
      }
      if (anyTouched) updatedCount += 1;
      const updated = {...binding};
      if (touched.input_type) {
        updated.input_type = form.input_type;
        updated.options = [...canonicalOptions];
      }
      if (touched.options) updated.options = [...canonicalOptions];
      if (touched.is_required) updated.is_required = !!form.is_required;
      if (touched.unit) updated.unit = form.unit || '';
      nextBindings.push(updated);
    });
    const freshCoords = coords.filter(
      coordinate => !this.bindingByCell[`${this.activeSheet}!${coordinate}`]);
    const names = batchFieldNames(form.field_name, freshCoords, this.activeSheet);
    const additions = freshCoords.map((coordinate, index) => ({
      field_id: uuidv4(),
      sheet_name: this.activeSheet,
      cell_coordinate: coordinate,
      field_name: names[index],
      input_type: form.input_type,
      is_required: !!form.is_required,
      unit: form.unit || '',
      options: canonicalOptions,
    }));
    const previous = this.current;
    this.current = {
      ...this.current,
      draft: {...this.draft, field_bindings: [...nextBindings, ...additions]},
    };
    try {
      await this.persist();
      await this.fetchDetail(this.current.id);
      this.resetSelection();
      this.selectedCell = '';
      if (updatedCount && additions.length) {
        message.success(`批量保存完成：更新 ${updatedCount} 个、新增 ${additions.length} 个字段`);
      } else if (updatedCount) {
        message.success(`批量修改完成：已更新 ${updatedCount} 个字段`);
      } else if (additions.length) {
        message.success(`已批量绑定 ${additions.length} 个字段`);
      } else {
        message.success('选区内已绑定字段保持不变');
      }
    } catch (e) {
      this.current = previous;
      throw e;
    }
  }

  /**
   * 批量解绑（独立操作，面板 Popconfirm 确认后调用）：移除选区内
   * （限当前工作表）全部已绑定字段并整体保存；失败回退本地数据。
   * persist 成功后 applyDetail 会顺带清空单格与批量选区。
   */
  @action async saveBatchUnbind() {
    if (!this.current || !this.selectedCells.length) return;
    const coords = toJS(this.selectedCells);
    const removing = this.bindings.filter(binding =>
      binding.sheet_name === this.activeSheet
      && coords.indexOf(binding.cell_coordinate) !== -1);
    if (!removing.length) return;
    const removingIds = new Set(removing.map(binding => binding.field_id));
    const previous = this.current;
    this.current = {
      ...this.current,
      draft: {
        ...this.draft,
        field_bindings: this.bindings.filter(
          binding => !removingIds.has(binding.field_id)),
      },
    };
    try {
      await this.persist();
      message.success(`已解绑 ${removing.length} 个字段`);
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

  /** 打开参数抽屉：以当前草稿参数预填表单（缺省项补全），样例数据清空。 */
  @action openPdfDrawer() {
    this.pdfForm = normalizePdfParams(toJS(this.pdfParams));
    this.sampleForm = {};
    this.pdfDrawerVisible = true;
  }

  @action closePdfDrawer() {
    this.pdfDrawerVisible = false;
    this.pdfForm = null;
    this.sampleForm = null;
  }

  @action setPdfForm(form) {
    this.pdfForm = form;
  }

  @action setSampleValue(fieldId, value) {
    this.sampleForm = {...this.sampleForm, [fieldId]: value};
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
   * 停用模板（逻辑停用，幂等）：停用后不可用于新台账，历史台账继续按
   * 创建时版本查看与导出；成功提示后重取列表（不做乐观停用），模板
   * 即从在用视图移出、进入已停用视图。
   * 失败由公共拦截器统一提示业务错误，这里不再重复弹窗，只向上传递拒绝。
   */
  async deactivateTemplate(templateId) {
    this.deletingId = templateId;
    try {
      await http.post(`${API}/${templateId}/deactivate/`);
      message.success('模板已停用');
      await this.fetchList();
    } finally {
      this.deletingId = '';
    }
  }

  /**
   * 重新启用模板（停用的逆操作，幂等）：启用后恢复用于新台账与本期
   * 应填台账自动生成，模板回到在用视图；成功提示后重取列表（不做
   * 乐观更新）。失败由公共拦截器统一提示业务错误，这里不再重复弹窗。
   */
  async activateTemplate(templateId) {
    this.deletingId = templateId;
    try {
      await http.post(`${API}/${templateId}/activate/`);
      message.success('模板已重新启用');
      await this.fetchList();
    } finally {
      this.deletingId = '';
    }
  }

  /**
   * 删除模板（物理删除）：后端在删除时重新检查引用关系（任一版本仍被
   * 台账引用时拒绝并提示）。成功后重取列表（被删除模板从列表消失）。
   */
  async destroyTemplate(templateId) {
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
   * 草稿 PDF 预览（已保存参数）：请求二进制后新窗口打开（弹窗被拦截时
   * 回退下载）。失败由公共拦截器统一提示业务错误（如 LibreOffice 不可用），
   * 这里不重复弹错、不做乐观成功提示；只读接口可重复调用。
   * 反馈（页数/纸张/提示）记入 previewInfo，参数来源标注"已保存参数"。
   */
  async previewPdf() {
    if (!this.current || !this.draft) return;
    this.previewing = true;
    try {
      const response = await http.post(
        `${API}/${this.current.id}/preview/pdf/`, null,
        {responseType: 'arraybuffer', timeout: 180000});
      this.openPdfResponse(response);
      this.previewInfo = {source: 'saved', ...parsePdfMetaHeaders(response)};
    } finally {
      this.previewing = false;
    }
  }

  /**
   * 应用当前设置并预览（2026-10-19）：以打印设置表单当前值（可含未保存
   * 修改）+ 临时样例数据请求预览，后端只作用于本次预览副本，不写草稿。
   * 序列化失败 warning 提示并返回 false（不发请求）；成功后反馈记入
   * previewInfo，参数来源标注"当前未保存参数"。
   */
  @action async previewWithFormParams() {
    if (!this.current || !this.pdfForm) return false;
    const {payload, error} = serializePdfParams(this.pdfForm);
    if (error) {
      message.warning(error);
      return false;
    }
    this.previewing = true;
    try {
      const response = await http.post(
        `${API}/${this.current.id}/preview/pdf/`,
        {pdf_params: payload, sample_values: toJS(this.sampleForm || {})},
        {responseType: 'arraybuffer', timeout: 180000});
      this.openPdfResponse(response);
      this.previewInfo = {source: 'form', ...parsePdfMetaHeaders(response)};
      return true;
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

  // ==================== 模板编辑页内打印预览（2026-10-21 统一观感） ====================

  _revokePrintPreviewUrl() {
    if (this.printPreviewUrl) {
      try {
        window.URL.revokeObjectURL(this.printPreviewUrl);
      } catch (e) {
        // URL 已释放时忽略
      }
    }
  }

  /** 重置页内预览（返回列表/切换模板时调用；blob URL 释放防泄漏）。 */
  @action resetPrintPreview() {
    this._revokePrintPreviewUrl();
    this.printPreviewUrl = '';
    this.printPreviewMeta = null;
    this.printPreviewError = '';
    this.printPreviewStale = false;
  }

  /**
   * 页内打印预览（打印预览视图）：POST preview/pdf/（草稿已保存打印
   * 参数）取二进制后以 blob URL 在当前页面 iframe 内展示——与「预览空白
   * 打印稿」同一后端生成服务，保证「预览 = 发布/导出的真实版式」。
   * 成功记录 X-El-Pdf-* 反馈（页数/纸张/提示）并清除过期标记；草稿在
   * 预览后再变更由 applyDetail 标记 printPreviewStale（页面提示刷新）。
   * 失败记录错误态可重试，业务错误由公共拦截器统一提示。
   */
  async fetchTemplatePrintPreview() {
    if (!this.current || this.printPreviewLoading) return '';
    action(() => {
      this.printPreviewLoading = true;
      this.printPreviewError = '';
    })();
    try {
      const response = await http.post(
        `${API}/${this.current.id}/preview/pdf/`, null,
        {responseType: 'arraybuffer', timeout: 180000});
      const bytes = response && response.data;
      if (!bytes || !bytes.byteLength) {
        throw new Error('预览内容为空');
      }
      const blob = new Blob([bytes], {type: 'application/pdf'});
      const url = window.URL.createObjectURL(blob);
      this._revokePrintPreviewUrl();
      return action(() => {
        this.printPreviewUrl = url;
        this.printPreviewMeta = {source: 'saved', ...parsePdfMetaHeaders(response)};
        this.printPreviewStale = false;
        return url;
      })();
    } catch (e) {
      action(() => {
        this.printPreviewError = '预览生成失败，可点击「刷新预览」重试';
      })();
      throw e;
    } finally {
      action(() => { this.printPreviewLoading = false; })();
    }
  }

  /**
   * 拉取版本列表：默认当前模板，也支持列表页按行指定 templateId
   * （不改动当前模板详情）；成功后打开版本抽屉并标注归属模板。
   */
  @action async showVersionsFor(record) {
    this.versionsOwner = record && record.name ? record.name : '';
    await this.fetchVersions(record ? record.id : undefined);
    this.versionsVisible = true;
  }

  async fetchVersions(templateId) {
    const id = templateId || (this.current && this.current.id);
    const res = await http.get(`${API}/${id}/versions/`);
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
