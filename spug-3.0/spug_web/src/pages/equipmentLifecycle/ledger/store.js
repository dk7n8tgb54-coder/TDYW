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
 * - 周期分组（2026-10-11，2026-10-14 增强）：fetchGroups 按 维护类型+周期
 *   拉取分页分组列表（后端切片），组内五状态统计；展开状态受控持久化
 *   （默认只展开本期，历史期次折叠，刷新后保留）；本期工作概览
 *   fetchOverview 提供本周/本月或本航季应填情况真实统计；两个视图的筛选
 *   字段各自独立（周期 f_* / 模板 t_*），互不混淆；
 * - 本期应填台账生成（2026-10-14 重构原一键新增）：fetchGeneratePreview
 *   拉取预览（将新建/已存在跳过/缺少可用版本/需人工处理），generate
 *   确认后按预览口径创建缺项，成功后刷新当前视图并展开本期组；
 * - 模板分组视图（2026-10-11）：viewMode 在"按维护周期/按模板查看"间切换；
 *   fetchTemplateGroups 拉取模板组统计（后端聚合，组内数量不受分页影响），
 *   openTemplateGroup 进入组内台账分页列表，refresh 按 当前视图+组内层级
 *   分发刷新（提交/作废/详情返回共用）；组内批量 PDF 导出（导出本模板
 *   台账）先取确认数据再按同口径 POST 生成合并 PDF；
 * - 旧可视化模板 TemplateStore 已随旧可视化模板路线删除（2026-10）；
 * - 错误提示统一由 http 拦截器弹出，业务代码不重复提示。
 */
import {observable, action} from 'mobx';
import {http, exportFile} from 'libs';
import {API_PREFIX_L} from './constants';

// 周期视图展开状态持久化（按台账类型隔离，刷新/重进页面后保留合理展开状态）
const EXPANDED_STORAGE_KEY = 'el_ledger_expanded_periods_';

function loadExpandedPeriods(ledgerType) {
  try {
    const raw = window.localStorage.getItem(EXPANDED_STORAGE_KEY + ledgerType);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed : null;
  } catch (e) {
    return null;
  }
}

function saveExpandedPeriods(ledgerType, keys) {
  try {
    window.localStorage.setItem(
      EXPANDED_STORAGE_KEY + ledgerType, JSON.stringify(keys || []));
  } catch (e) {
    // 存储不可用（隐私模式等）时静默降级：仅本次会话内保留
  }
}

export class LedgerStore {
  ledgerType; // week_month | seasonal

  @observable records = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable isFetching = false;

  // —— 按维护周期视图筛选（与按模板查看视图各自独立，互不混淆） ——
  @observable f_keyword = undefined;
  @observable f_status = undefined;
  @observable f_system = undefined;
  // —— 按模板查看视图筛选 ——
  @observable t_keyword = undefined;
  @observable t_status = undefined;
  @observable t_date_range = undefined; // 日期范围 [moment, moment]

  @observable groups = [];
  @observable groupsTotal = 0;
  @observable groupsPage = 1;
  @observable groupsPageSize = 6; // 历史期次较多时分页加载，不再无限制全部展开
  @observable isGroupsFetching = false;
  // 周期分组展开状态（受控）：默认只展开本期，历史期次折叠，变更持久化
  @observable expandedPeriodKeys = [];
  @observable groupsVersion = 0; // 自增键：分组表格重渲染（数据更新）用
  @observable systemOptions = [];

  // 本期工作概览（2026-10-14）：本周/本月或本航季应填情况真实统计
  @observable overview = null;
  @observable isOverviewFetching = false;

  @observable viewMode = 'period'; // period 按维护周期 | template 按模板查看
  @observable templateGroups = [];
  @observable templateGroupsTotal = 0;
  @observable templateGroupsPage = 1;
  @observable templateGroupsPageSize = 10;
  @observable isTemplateGroupsFetching = false;
  @observable activeGroup = null; // {group_key, group_name} 进入的模板组
  @observable groupLedgers = [];
  @observable groupLedgersTotal = 0;
  @observable groupLedgersPage = 1;
  @observable groupLedgersPageSize = 20;
  @observable isGroupLedgersFetching = false;
  // 组内批量 PDF 导出（"导出本模板台账"）：确认框数据 + 生成下载
  @observable batchExportPreview = null; // 后端确认数据（模板名/数量/范围/版本）
  @observable isBatchExportFetching = false;

  // 本期应填台账生成（2026-10-14）：预览数据 + 请求态
  @observable generatePreview = null;   // 后端预览（entries + summary）
  @observable generatePeriodResult = null; // 确认生成后的实际结果（created/skipped/failed）
  @observable isGenerateFetching = false;
  @observable isGenerating = false;

  @observable detailVisible = false;
  @observable detail = {};
  @observable isDetailFetching = false;
  @observable isDeleting = false; // 台账物理删除请求进行中（删除确认按钮 loading）
  @observable isCorrecting = false; // 更正已完成台账明细请求进行中

  // 首次周期分组加载前是否已有持久化展开状态（无则默认只展开本期）
  _expandedInitialized = false;
  // 生成成功后要求下一轮分组把本期组展开（新台账立即可见）
  _ensureCurrentExpanded = false;

  constructor(ledgerType) {
    this.ledgerType = ledgerType;
    const saved = loadExpandedPeriods(ledgerType);
    if (saved !== null) {
      this.expandedPeriodKeys = saved;
      this._expandedInitialized = true;
    }
  }

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_status = undefined;
    this.f_system = undefined;
    this.page = 1;
  };

  /** 模板视图共用筛选参数（组列表与组内列表同口径；与周期视图筛选隔离）。 */
  templateFilterParams() {
    const params = {};
    if (this.t_keyword) params.keyword = this.t_keyword;
    if (this.t_status) params.status = this.t_status;
    if (this.t_date_range && this.t_date_range.length === 2) {
      params.executed_from = this.t_date_range[0].format('YYYY-MM-DD');
      params.executed_to = this.t_date_range[1].format('YYYY-MM-DD');
    }
    return params;
  }

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize, ledger_type: this.ledgerType};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
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
    const params = {
      ledger_type: this.ledgerType,
      page: this.groupsPage,
      page_size: this.groupsPageSize,
    };
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
    if (this.f_keyword) params.keyword = this.f_keyword;
    return http.get(`${API_PREFIX_L}/ledgers/period-groups/`, {params})
      .then(action(res => {
        // 兼容两种形态：分页 {data: {data, total}}（当前）与旧版裸列表 {data: [...]}
        const payload = res && res.data;
        if (Array.isArray(payload)) {
          this.groups = payload;
          this.groupsTotal = payload.length;
        } else {
          this.groups = (payload && payload.data) || [];
          this.groupsTotal = (payload && payload.total) || 0;
        }
        this.applyExpandedPeriods();
        this.groupsVersion += 1;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isGroupsFetching = false;
      }));
  };

  /**
   * 周期分组展开状态：默认只展开本期（is_current），历史期次折叠；
   * 用户手动展开/折叠与刷新（提交/作废/返回详情）后的分组更新都会保留，
   * 生成成功后强制展开本期让新台账立即可见；变更持久化到 localStorage。
   */
  @action applyExpandedPeriods = () => {
    const currentKeys = this.groups
      .filter(g => g.is_current)
      .map(g => g.maintenance_period);
    let keys = [...this.expandedPeriodKeys];
    if (this._ensureCurrentExpanded) {
      keys = Array.from(new Set([...keys, ...currentKeys]));
      this._ensureCurrentExpanded = false;
    } else if (!this._expandedInitialized) {
      // 无持久化状态时的首次加载：默认只展开本期
      keys = Array.from(new Set([...keys, ...currentKeys]));
      this._expandedInitialized = true;
    }
    this.expandedPeriodKeys = keys;
    saveExpandedPeriods(this.ledgerType, keys);
  };

  @action togglePeriodExpanded = (keys) => {
    this.expandedPeriodKeys = keys || [];
    saveExpandedPeriods(this.ledgerType, this.expandedPeriodKeys);
  };

  @action setGroupsPage = (page) => {
    this.groupsPage = page;
    this.fetchGroups();
  };

  fetchOverview = () => {
    this.isOverviewFetching = true;
    return http.get(`${API_PREFIX_L}/ledgers/period-overview/`, {
      params: {ledger_type: this.ledgerType}})
      .then(action(res => {
        this.overview = res && res.data ? res.data : res;
        return this.overview;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isOverviewFetching = false;
      }));
  };

  fetchTemplateGroups = () => {
    this.isTemplateGroupsFetching = true;
    const params = {
      ledger_type: this.ledgerType,
      page: this.templateGroupsPage,
      page_size: this.templateGroupsPageSize,
      ...this.templateFilterParams(),
    };
    return http.get(`${API_PREFIX_L}/ledgers/template-groups/`, {params})
      .then(action(res => {
        this.templateGroups = (res && res.data) || [];
        this.templateGroupsTotal = (res && res.total) || 0;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isTemplateGroupsFetching = false;
      }));
  };

  fetchGroupLedgers = () => {
    if (!this.activeGroup) return Promise.resolve();
    this.isGroupLedgersFetching = true;
    const params = {
      ledger_type: this.ledgerType,
      page: this.groupLedgersPage,
      page_size: this.groupLedgersPageSize,
      ...this.templateFilterParams(),
    };
    return http.get(
      `${API_PREFIX_L}/ledgers/template-groups/${this.activeGroup.group_key}/ledgers/`,
      {params})
      .then(action(res => {
        this.groupLedgers = (res && res.data) || [];
        this.groupLedgersTotal = (res && res.total) || 0;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isGroupLedgersFetching = false;
      }));
  };

  @action setViewMode = (mode) => {
    if (this.viewMode === mode) return;
    this.viewMode = mode;
    if (mode === 'template') {
      this.activeGroup = null;
      this.templateGroupsPage = 1;
      this.fetchTemplateGroups();
    } else {
      this.fetchOverview();
      this.fetchGroups();
    }
  };

  @action openTemplateGroup = (group) => {
    this.activeGroup = {group_key: group.group_key, group_name: group.template_name};
    this.groupLedgersPage = 1;
    this.fetchGroupLedgers();
  };

  @action backToGroups = () => {
    // 返回模板组列表：保留组列表筛选与页码
    this.activeGroup = null;
    this.fetchTemplateGroups();
  };

  /** 组内批量导出筛选参数：与组内列表同口径（确认与生成两次请求共用）。 */
  batchExportParams() {
    return {ledger_type: this.ledgerType, ...this.templateFilterParams()};
  }

  /** 明细 CSV 导出参数：与周期视图当前筛选同口径（编号/状态/按系统查看）。 */
  periodExportParams() {
    const params = {ledger_type: this.ledgerType};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_status) params.status = this.f_status;
    if (this.f_system) params.system = this.f_system;
    return params;
  }

  /** 点击"导出本模板台账"：先取后端确认数据（模板名/数量/日期范围/状态范围/版本）。 */
  openBatchExport = () => {
    if (!this.activeGroup) return Promise.resolve();
    this.isBatchExportFetching = true;
    return http.get(
      `${API_PREFIX_L}/ledgers/template-groups/${this.activeGroup.group_key}/export-pdf/`,
      {params: this.batchExportParams()})
      .then(action(res => {
        this.batchExportPreview = (res && res.data) ? res.data : res;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isBatchExportFetching = false;
      }));
  };

  @action closeBatchExport = () => {
    this.batchExportPreview = null;
  };

  /** 确认后实际导出：POST 同口径筛选，exportFile 二进制下载合并 PDF。 */
  exportBatchPdf = () => {
    if (!this.activeGroup) return Promise.resolve();
    return exportFile({
      url: `${API_PREFIX_L}/ledgers/template-groups/${this.activeGroup.group_key}/export-pdf/`,
      method: 'post',
      params: this.batchExportParams(),
      defaultFilename: `${this.activeGroup.group_name}-批量导出.pdf`,
      timeout: 300000,
      loadingText: '正在生成 PDF...',
    });
  };

  /** 按当前视图与层级刷新（完成/作废/删除/详情返回共用，避免跨视图错刷）。
   *
   * 周期视图同时刷新本期工作概览（数量与列表保持一致）。
   */
  refresh = () => {
    if (this.viewMode === 'period') {
      return Promise.all([this.fetchGroups(), this.fetchOverview()]);
    }
    if (this.activeGroup) return this.fetchGroupLedgers();
    return this.fetchTemplateGroups();
  };

  fetchSystemOptions = () => {
    return http.get(`${API_PREFIX_L}/ledgers/batch-create/`)
      .then(action(res => {
        this.systemOptions = (res && res.data) || [];
      }))
      .catch(action(() => {}));
  };

  /** 本期应填台账预览（只读）：逐模板给出当前期次与可生成性判定。 */
  fetchGeneratePreview = (ledgerType) => {
    this.isGenerateFetching = true;
    this.generatePeriodResult = null;
    return http.get(`${API_PREFIX_L}/ledgers/period-generate/`, {
      params: {ledger_type: ledgerType || this.ledgerType}})
      .then(action(res => {
        this.generatePreview = res && res.data ? res.data : res;
        return this.generatePreview;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isGenerateFetching = false;
      }));
  };

  /**
   * 确认生成：后端按预览同口径重算并创建缺项，返回实际结果
   * （created/skipped/failed）；成功后按当前视图刷新列表让新草稿可见。
   */
  generatePeriodLedgers = (ledgerType) => {
    this.isGenerating = true;
    return http.post(`${API_PREFIX_L}/ledgers/period-generate/`, {
      ledger_type: ledgerType || this.ledgerType})
      .then(action(res => {
        const result = res && res.data ? res.data : res;
        this.generatePeriodResult = result;
        // 生成成功后强制展开本期组，新台账立即可见
        if (result && Array.isArray(result.created) && result.created.length) {
          this._ensureCurrentExpanded = true;
        }
        this.refresh();
        return result;
      }))
      .finally(action(() => {
        this.isGenerating = false;
      }));
  };

  /**
   * 明确补建（2026-10-16）：为"已作废占用"的本期槽位重新生成应填台账。
   * 成功后强制展开本期组并刷新当前视图。
   */
  rebuildPeriodLedger = (templateId) => {
    this.isGenerating = true;
    return http.post(`${API_PREFIX_L}/ledgers/period-generate/rebuild/`, {
      template_id: templateId})
      .then(action(res => {
        const row = res && res.data ? res.data : res;
        this._ensureCurrentExpanded = true;
        this.refresh();
        return row;
      }))
      .finally(action(() => {
        this.isGenerating = false;
      }));
  };

  /** 作废（受控，须填原因）；成功后按当前视图刷新。 */
  voidLedger = (id, reason) => {
    return http.post(`${API_PREFIX_L}/ledgers/${id}/void/`, {reason})
      .then(action(() => {
        this.refresh();
      }));
  };

  /** 物理删除台账（草稿/旧流程历史状态；已完成与已作废由后端拒绝）。 */
  deleteLedger = (id) => {
    this.isDeleting = true;
    return http.delete(`${API_PREFIX_L}/ledgers/${id}/`)
      .then(action(() => {
        this.refresh();
      }))
      .finally(action(() => {
        this.isDeleting = false;
      }));
  };

  /** 更正已完成台账的单条明细（须填原因；后端记录修改人/时间/前后值）。 */
  correctLedgerItem = (itemId, body) => {
    this.isCorrecting = true;
    return http.post(`${API_PREFIX_L}/ledgers/${this.detail.id}/correct/`, {
      item_id: itemId, ...body})
      .then(action(() => {
        this.refresh();
        return this.fetchDetail(this.detail.id);
      }))
      .finally(action(() => {
        this.isCorrecting = false;
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
