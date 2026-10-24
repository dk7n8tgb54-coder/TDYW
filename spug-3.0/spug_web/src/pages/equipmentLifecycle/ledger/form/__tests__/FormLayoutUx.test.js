/**
 * 数字表单前端布局与填写控件呈现测试（2026-10-24 两项 UX 修复）。
 *
 * 真实渲染（ReactDOM + jsdom，antd 真组件）+ mock libs/http，验证：
 * 一、编辑器桌面三栏：抽屉 body 不再整页滚动，长画布在中栏内部滚动，
 *     左分组目录与右检查器为独立滚动容器（浏览长画布时保持可见可操作）；
 *     窄屏（<992）维持既有整页滚动与"选中项设置"抽屉，不强行三栏；
 *     左栏点击选中/画布高亮联动不回归；
 * 二、填写控件宽度上限：text/number/date/choice 按类型限宽（width:100%
 *     窄容器仍自适应），textarea 保持整行宽并以模板 rows 为初值自动
 *     增高；异常说明（普通字段/矩阵集中区）多行可增长、长内容可继续
 *     输入；矩阵少列时单元格控件限宽，宽矩阵列 minWidth 保留且表格置于
 *     横向滚动容器内（容器不足时组内滚动，不撑破卡片/弹窗）；
 *     编辑器底部操作条可换行（窄屏发布按钮保持可达）；
 * 三、共用渲染层三个入口一致：台账填写页（FormLedgerDetail）、编辑器
 *     试填预览（PreviewModal）、模板画布禁用态展示（FillWidget）。
 *
 * 2026-10-24 浏览器验收补充：宽矩阵溢出与底部按钮不可达两缺陷在真实
 * 布局中复现并修复（quality/reports/el_form_fill_ux/），本文件补回归。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  const AuthButton = (props) => React.createElement('button', {
    type: 'button', 'data-testid': props['data-testid'],
    onClick: props.onClick, disabled: props.disabled,
  }, props.children);
  return {
    AuthDiv: Shell, AuthButton, AuthCard: Shell, AuthFragment: Shell,
    Breadcrumb: Shell, SearchForm: Shell, ExportButton: AuthButton,
    TableCard: Shell,
  };
});

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const FormTemplateEditor = require('../FormTemplateEditor').default;
const FormFillRenderer = require('../FormFillRenderer').default;
const {applyFillEdit} = require('../FormFillRenderer');
const FormLedgerDetail = require('../FormLedgerDetail').default;
const {formTemplateStore} = require('../formTemplateStore');
const {FormLedgerStore} = require('../formLedgerStore');

/** 可编辑渲染 harness：onEdit 经 applyFillEdit 真实回写 values 并重渲
 * 染（与 formLedgerStore.edit 同一纯函数路径），受控输入行为与真实
 * 填写页一致。 */
class EditableRenderer extends React.Component {
  constructor(props) {
    super(props);
    this.state = {values: props.values || {}};
  }
  render() {
    return h(FormFillRenderer, {
      form: this.props.form, values: this.state.values, editable: true,
      onEdit: (...args) => this.setState(
        prev => ({values: applyFillEdit(prev.values, ...args)})),
    });
  }
}

/** 填写控件宽度契约（FormFillRenderer 共享层）：宽容器下按类型封顶。 */
const EXPECT_TEXT_CAP = '480px';
const EXPECT_NUMBER_CAP = '220px';
const EXPECT_DATE_CAP = '220px';
const EXPECT_CHOICE_CAP = '320px';
const EXPECT_MATRIX_CELL_CAP = '200px';

/** 宽表单：覆盖六种字段类型 + 少列矩阵（2 列）与宽矩阵（8 列）。 */
const WIDE_FORM = {
  protocol_version: 2,
  groups: [
    {id: 'g_base', name: '基本信息', description: '', kind: 'fields',
     item_name: '', columns: [], fields: [
       {id: 'f_text', name: '处理人', type: 'text', required: false,
        description: '', unit: '', options: []},
       {id: 'f_num', name: '供电电压', type: 'number', required: false,
        description: '', unit: 'V', options: []},
       {id: 'f_date', name: '维护日期', type: 'date', required: false,
        description: '', unit: '', options: []},
       {id: 'f_choice', name: '处理方式', type: 'choice', required: false,
        description: '', unit: '', options: ['更换', '紧固', '清洁']},
       {id: 'f_area', name: '维护记录', type: 'textarea', required: false,
        description: '', unit: '', options: [], rows: 4},
       {id: 'f_abn', name: '外观检查', type: 'normal_abnormal',
        required: false, description: '', unit: '', options: [],
        require_desc_when_abnormal: true},
     ]},
    {id: 'g_matrix2', name: '少列对比', description: '', kind: 'matrix',
     item_name: '', columns: [
       {id: 'c_m2a', name: 'A 机'}, {id: 'c_m2b', name: 'B 机'}], fields: [
       {id: 'r_m2num', name: '输出电压', type: 'number', required: false,
        description: '', unit: 'V', options: []},
       {id: 'r_m2txt', name: '固件版本', type: 'text', required: false,
        description: '', unit: '', options: []},
       {id: 'r_m2abn', name: '通讯状态', type: 'normal_abnormal',
        required: false, description: '', unit: '', options: [],
        require_desc_when_abnormal: true},
     ]},
    {id: 'g_matrix8', name: '宽矩阵对比', description: '', kind: 'matrix',
     item_name: '', columns: ['c_w1', 'c_w2', 'c_w3', 'c_w4', 'c_w5',
       'c_w6', 'c_w7', 'c_w8'].map((id, i) => ({id, name: `${i + 1} 号机`})),
     fields: [
       {id: 'r_w1num', name: '输出电压', type: 'number', required: false,
        description: '', unit: 'V', options: []},
     ]},
  ],
};

const WIDE_VALUES = {
  f_abn: 'abnormal',
  g_matrix2: {r_m2abn: {c_m2a: 'abnormal'}},
};

/** 长表单：12 个分组制造长画布（编辑器滚动场景）。 */
const LONG_FORM = {
  protocol_version: 2,
  groups: Array.from({length: 12}, (unused, index) => ({
    id: `g_long${String(index + 1).padStart(2, '0')}`,
    name: `检查分组 ${index + 1}`, description: '', kind: 'fields',
    item_name: '', columns: [],
    fields: [
      {id: `f_long${index}a`, name: '外观状态', type: 'normal_abnormal',
       required: false, description: '', unit: '', options: []},
      {id: `f_long${index}b`, name: '处理人', type: 'text', required: false,
       description: '', unit: '', options: []},
    ],
  })),
};

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const flushAll = async () => { await flush(); await flush(); await flush(); };

function render(node) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  ReactDOM.render(node, container);
  return {container, cleanup: () => {
    ReactDOM.unmountComponentAtNode(container);
    document.querySelectorAll(
      '.ant-modal-root, .ant-drawer-root, .ant-modal-confirm, .ant-popover')
      .forEach(node => node.remove());
    container.remove();
  }};
}

function setTextarea(ta, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set;
  act(() => {
    setter.call(ta, value);
    ta.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

/** 取控件实际承宽元素：InputNumber/DatePicker/Select 的 style 在外层
 * 包装元素上（.ant-input-number/.ant-picker/.ant-select），Input 与
 * TextArea 的 style 就在元素自身。 */
function widthHostOf(testId, root) {
  const scope = root || document;
  const el = scope.querySelector(`[data-testid="${testId}"]`);
  if (!el) return null;
  return el.closest('.ant-input-number, .ant-picker, .ant-select') || el;
}

function resetTemplateStore() {
  const store = formTemplateStore;
  store.list = []; store.isFetching = false; store.detail = null;
  store.createVisible = false; store.createOptions = null; store.creating = false;
  store.editorVisible = false; store.editorTemplate = null;
  store.editorLoading = false; store.editorLoadError = '';
  store.savingDraft = false; store.publishing = false;
  store.versionsVisible = false; store.versionsTemplate = null;
  store.versions = []; store.versionDetail = null;
  store.keyword = ''; store.ledgerTypeFilter = '';
}

/** 打开模板编辑器并等待草稿加载完成。 */
async function openEditorWith(form) {
  mockHttpGet.mockImplementation(url =>
    String(url).endsWith('/form-templates/12/')
      ? Promise.resolve({data: {
        id: 12, name: '周维护数字表单', ledger_type: 'week_month',
        description: '', system: null, system_name: '', generation_period: '',
        generation_period_text: '待配置', is_active: true, has_draft: true,
        latest_version_no: 0, versions_count: 0, ledgers_count: 0,
        status: 'draft',
        draft: {form, updated_at: '2026-10-23T10:00:00', updated_by: '张三'},
        draft_state: {relation: 'modified', latest_version_no: 0,
                      versions_count: 0, field_count: 24,
                      updated_at: '2026-10-23T10:00:00'},
      }})
      : Promise.reject('意外请求：' + url));
  act(() => { formTemplateStore.openEditor({
    id: 12, name: '周维护数字表单', ledger_type: 'week_month',
    description: '', system: null, system_name: '', generation_period: '',
    generation_period_text: '待配置', is_active: true, has_draft: true,
    latest_version_no: 0, versions_count: 0, ledgers_count: 0,
    status: 'draft',
  }); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  return view;
}

beforeEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
  resetTemplateStore();
  window.innerWidth = 1024;
});

// ==================== 一、编辑器三栏布局 ====================

describe('编辑器桌面三栏：长画布滚动时两侧面板保持可见', () => {
  test('抽屉 body 固定高度，画布中栏内部滚动，左目录/右检查器独立滚动', async () => {
    const view = await openEditorWith(LONG_FORM);
    const drawerBody = document.querySelector('.ant-drawer-body');
    expect(drawerBody).toBeTruthy();
    // 抽屉 body 不再是整页滚动容器（高度固定，滚动下沉到各栏内部）
    expect(drawerBody.style.display).toBe('flex');
    expect(drawerBody.style.flexDirection).toBe('column');
    expect(drawerBody.style.overflow).toBe('hidden');
    // 左栏：分组目录独立滚动
    const groupList = document.querySelector(
      '[data-testid="editor-group-list"]');
    expect(groupList).toBeTruthy();
    expect(groupList.style.overflowY).toBe('auto');
    expect(groupList.querySelector('[data-testid="editor-group-g_long01"]'))
      .toBeTruthy();
    // 中栏：画布滚动容器内含全部分组（长内容滚动只发生在中栏）
    const canvasScroll = document.querySelector(
      '[data-testid="editor-canvas-scroll"]');
    expect(canvasScroll).toBeTruthy();
    expect(canvasScroll.style.overflowY).toBe('auto');
    expect(canvasScroll.querySelector('[data-testid="form-template-canvas"]'))
      .toBeTruthy();
    expect(canvasScroll.querySelector('[data-testid="canvas-group-g_long12"]'))
      .toBeTruthy();
    // 右栏：检查器面板独立滚动（未选中时占位提示也在滚动容器内）
    const inspectorScroll = document.querySelector(
      '[data-testid="editor-inspector-scroll"]');
    expect(inspectorScroll).toBeTruthy();
    expect(inspectorScroll.style.overflowY).toBe('auto');
    // 未锁定时编辑区可交互
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).not.toBe('none');
    view.cleanup();
  });

  test('左栏点击分组仍选中并高亮画布分组（滚动布局不破坏联动）', async () => {
    const view = await openEditorWith(LONG_FORM);
    await act(async () => {
      document.querySelector('[data-testid="editor-group-g_long07"]').click();
    });
    const card = document.querySelector('[data-testid="canvas-group-g_long07"]');
    expect(card.getAttribute('style')).toContain('91d5ff');
    const inspector = document.querySelector(
      '[data-testid="editor-inspector-scroll"]');
    // 右栏同步显示该分组设置（名称在输入框值中）
    expect(inspector.textContent).toContain('分组设置');
    expect(inspector.querySelector('[data-testid="inspector-group-name"]').value)
      .toBe('检查分组 7');
    view.cleanup();
  });

  test('底部操作条可换行：窄屏按钮总宽超容器时折行，发布按钮保持可达', async () => {
    const view = await openEditorWith(LONG_FORM);
    const footerBar = document.querySelector('.ant-drawer-footer > div');
    expect(footerBar).toBeTruthy();
    // 容器换行（2026-10-24 浏览器实测：390px 视口下底部按钮排 621px
    // 溢出，「发布版本」被渲染到视口外不可点击）
    expect(footerBar.style.flexWrap).toBe('wrap');
    // 两组按钮（左侧预览组/右侧保存发布组）各自可换行（antd Space wrap
    // 以内联 flexWrap 渲染）
    const spaces = Array.from(footerBar.querySelectorAll('.ant-space'));
    expect(spaces.length).toBe(2);
    for (const space of spaces) {
      expect(space.style.flexWrap).toBe('wrap');
    }
    expect(footerBar.textContent).toContain('发布版本');
    view.cleanup();
  });
});

describe('编辑器窄屏：维持整页滚动与检查器抽屉', () => {
  test('窄屏不启用三栏固定高度，检查器仍走 Drawer', async () => {
    window.innerWidth = 900;
    const view = await openEditorWith(LONG_FORM);
    const drawerBody = document.querySelector('.ant-drawer-body');
    // 窄屏抽屉 body 保持默认整页滚动（不 overflow hidden）
    expect(drawerBody.style.overflow).not.toBe('hidden');
    const canvasScroll = document.querySelector(
      '[data-testid="editor-canvas-scroll"]');
    expect(canvasScroll).toBeTruthy();
    expect(canvasScroll.style.overflowY).not.toBe('auto');
    // 窄屏右栏不渲染固定面板
    expect(document.querySelector(
      '[data-testid="editor-inspector-panel"]')).toBeNull();
    // 点击画布字段 → 检查器进入"选中项设置"抽屉（既有交互）
    await act(async () => {
      document.querySelector('[data-testid="canvas-field-f_long0a"]').click();
    });
    const titles = Array.from(
      document.querySelectorAll('.ant-drawer-title'))
      .map(node => node.textContent);
    expect(titles).toContain('选中项设置');
    view.cleanup();
  });
});

// ==================== 二、填写控件宽度与长文本 ====================

describe('填写控件宽度：按类型上限，宽容器不无限拉长', () => {
  test('text/number/date/choice 限宽且 width:100%，textarea 保持整行宽', () => {
    const view = render(h(FormFillRenderer, {
      form: WIDE_FORM, values: WIDE_VALUES, editable: true,
      onEdit: () => {},
    }));
    const cases = [
      ['field-control-f_text', EXPECT_TEXT_CAP],
      ['field-control-f_num', EXPECT_NUMBER_CAP],
      ['field-control-f_date', EXPECT_DATE_CAP],
      ['field-control-f_choice', EXPECT_CHOICE_CAP],
    ];
    for (const [testId, cap] of cases) {
      const host = widthHostOf(testId);
      expect(host).toBeTruthy();
      expect(host.style.width).toBe('100%');
      expect(host.style.maxWidth).toBe(cap);
    }
    // 多行文本保持整行宽（不设上限），rows 初值来自模板
    const area = document.querySelector('[data-testid="field-control-f_area"]');
    expect(area.tagName).toBe('TEXTAREA');
    expect(area.style.width).toBe('100%');
    expect(area.style.maxWidth).toBe('');
    view.cleanup();
  });

  test('textarea 按模板 rows 为初值自动增高，长内容可继续输入', () => {
    const view = render(h(EditableRenderer, {form: WIDE_FORM, values: {}}));
    const area = document.querySelector('[data-testid="field-control-f_area"]');
    // rows=4 为初值行数；autoSize 生效（resize 关闭、随内容增高）——
    // rc-textarea 的 autoSize 样式在挂载/输入 effect 后写入，输入后断言
    expect(area.getAttribute('rows')).toBe('4');
    const longText = '逐项检查正常。'.repeat(60);
    setTextarea(area, longText);
    expect(area.value).toBe(longText);
    expect(area.style.resize).toBe('none');
    view.cleanup();
  });

  test('异常说明多行可增长：普通字段与矩阵集中说明区长内容可继续输入', () => {
    const view = render(h(EditableRenderer, {
      form: WIDE_FORM, values: WIDE_VALUES}));
    // 普通字段异常说明（f_abn=abnormal 触发内联说明）
    const fieldDesc = document.querySelector(
      '[data-testid="abnormal-desc-f_abn"]');
    expect(fieldDesc).toBeTruthy();
    const faultText = '端子排 X3 松动，已紧固并复测正常。'.repeat(20);
    setTextarea(fieldDesc, faultText);
    expect(fieldDesc.value).toBe(faultText);
    expect(fieldDesc.style.resize).toBe('none');
    // 矩阵集中异常说明（r_m2abn × c_m2a=abnormal）：同为多行可增长控件
    const descs = Array.from(
      view.container.querySelectorAll('textarea'))
      .filter(ta => ta.getAttribute('placeholder') === '异常说明（必填）');
    expect(descs.length).toBe(2);
    setTextarea(descs[1], 'A 机通讯闪断，更换通讯板后恢复。'.repeat(20));
    expect(descs[1].value.length).toBeGreaterThan(100);
    expect(descs[1].style.resize).toBe('none');
    view.cleanup();
  });
});

describe('矩阵单元格控件：少列限宽，宽矩阵保留列宽可读性', () => {
  test('少列矩阵单元格控件限宽（三种类型一致）', () => {
    const view = render(h(FormFillRenderer, {
      form: WIDE_FORM, values: {}, editable: true, onEdit: () => {},
    }));
    const hosts = [
      widthHostOf('cell-control-r_m2num-c_m2a', view.container),
      widthHostOf('cell-control-r_m2txt-c_m2a', view.container),
    ];
    for (const host of hosts) {
      expect(host).toBeTruthy();
      expect(host.style.width).toBe('100%');
      expect(host.style.maxWidth).toBe(EXPECT_MATRIX_CELL_CAP);
    }
    // 正常/异常单元格 Select 保留既有 matrix-cell-* testid，按结构定位：
    // 矩阵表格内（td 下）的 Select 即单元格控件
    const cellSelect = Array.from(
      view.container.querySelectorAll('.ant-select'))
      .find(el => el.closest('td'));
    expect(cellSelect).toBeTruthy();
    expect(cellSelect.style.width).toBe('100%');
    expect(cellSelect.style.maxWidth).toBe(EXPECT_MATRIX_CELL_CAP);
    view.cleanup();
  });

  test('宽矩阵（8 列）列 minWidth 保留，表格在横向滚动容器内不撑破容器', () => {
    const view = render(h(FormFillRenderer, {
      form: WIDE_FORM, values: {}, editable: true, onEdit: () => {},
    }));
    // 列头 minWidth 140 保留（既有横向适配/可读性）
    const ths = Array.from(view.container.querySelectorAll('table th'))
      .filter(th => th.textContent.includes('号机'));
    expect(ths.length).toBe(8);
    for (const th of ths) {
      expect(th.style.minWidth).toBe('140px');
    }
    const host = widthHostOf('cell-control-r_w1num-c_w1', view.container);
    expect(host).toBeTruthy();
    expect(host.style.maxWidth).toBe(EXPECT_MATRIX_CELL_CAP);
    // 横向滚动容器（2026-10-24 实测：820px 预览弹窗中 8 列表格 1172px
    // 溢出到弹窗盒之外、最右列不可见不可填）：宽矩阵与少列矩阵一致包裹，
    // 容器不足时组内横向滚动
    for (const groupId of ['g_matrix2', 'g_matrix8']) {
      const scrollBox = view.container.querySelector(
        `[data-testid="matrix-table-scroll-${groupId}"]`);
      expect(scrollBox).toBeTruthy();
      expect(scrollBox.style.overflowX).toBe('auto');
      expect(scrollBox.querySelector('table')).toBeTruthy();
    }
    view.cleanup();
  });
});

// ==================== 三、三个入口一致 ====================

describe('共用渲染层三个入口：填写页 / 试填预览 / 模板画布', () => {
  test('台账填写页（FormLedgerDetail）真实渲染中控件同样限宽', async () => {
    mockHttpGet.mockImplementation(url =>
      String(url).endsWith('/form-ledgers/55/')
        ? Promise.resolve({data: {
          id: 55, ledger_no: 'EL-WM-20261024-0001', ledger_type: 'week_month',
          status: 'draft', system_name: 'ILS 系统',
          maintenance_period: '2026-10-24', created_by_name: '张三',
          completed_at: null, void_reason: '',
          form: {record_id: 9, values: WIDE_VALUES, editable: true,
                 voided: false,
                 version: {id: 3, version_no: 2, template_name: '周维护数字表单',
                           form: WIDE_FORM}},
        }})
        : Promise.reject('意外请求：' + url));
    const store = new FormLedgerStore();
    await store.fetchDetail(55);
    const view = render(h(FormLedgerDetail, {store, onBack: jest.fn()}));
    const textHost = widthHostOf('field-control-f_text', view.container);
    expect(textHost.style.maxWidth).toBe(EXPECT_TEXT_CAP);
    const numHost = widthHostOf('field-control-f_num', view.container);
    expect(numHost.style.maxWidth).toBe(EXPECT_NUMBER_CAP);
    const cellHost = widthHostOf('cell-control-r_m2num-c_m2a', view.container);
    expect(cellHost.style.maxWidth).toBe(EXPECT_MATRIX_CELL_CAP);
    // 填写页矩阵表格同样置于横向滚动容器内（共用渲染层一致）
    const pageScrollBox = view.container.querySelector(
      '[data-testid="matrix-table-scroll-g_matrix2"]');
    expect(pageScrollBox).toBeTruthy();
    expect(pageScrollBox.style.overflowX).toBe('auto');
    view.cleanup();
  });

  test('编辑器试填预览与模板画布禁用态同样应用宽度契约', async () => {
    const form = {
      protocol_version: 2,
      groups: [WIDE_FORM.groups[0], WIDE_FORM.groups[1]],
    };
    const view = await openEditorWith(form);
    // 画布禁用态展示（FillWidget → FieldInput）
    const canvasHost = widthHostOf('field-control-f_text');
    expect(canvasHost.style.maxWidth).toBe(EXPECT_TEXT_CAP);
    // 画布矩阵单元格（MatrixCellInput 不携带 cell-control testid，按
    // canvas-matrix 结构定位数字单元格控件验证同一限宽）
    const canvasCell = document.querySelector(
      '[data-testid="canvas-matrix-g_matrix2"] td .ant-input-number');
    expect(canvasCell).toBeTruthy();
    expect(canvasCell.style.maxWidth).toBe(EXPECT_MATRIX_CELL_CAP);
    // 试填预览弹窗（PreviewModal → FormFillRenderer editable）
    await act(async () => {
      document.querySelector('[data-testid="editor-preview"]').click();
    });
    await act(flushAll);
    const modalHost = widthHostOf(
      'field-control-f_text', document.querySelector('.ant-modal-body'));
    expect(modalHost).toBeTruthy();
    expect(modalHost.style.maxWidth).toBe(EXPECT_TEXT_CAP);
    const modalCell = widthHostOf(
      'cell-control-r_m2num-c_m2a', document.querySelector('.ant-modal-body'));
    expect(modalCell.style.maxWidth).toBe(EXPECT_MATRIX_CELL_CAP);
    // 试填预览弹窗（820px）中矩阵表格同样在横向滚动容器内
    const modalScrollBox = document.querySelector(
      '.ant-modal-body [data-testid="matrix-table-scroll-g_matrix2"]');
    expect(modalScrollBox).toBeTruthy();
    expect(modalScrollBox.style.overflowX).toBe('auto');
    view.cleanup();
  });
});
