/**
 * 运行处置记录——列表页与新增/编辑表单渲染契约测试（2026-10-11 合并改造；
 * 2026-10-15 拆分：详情窗口相关用例移至 detailWindow.test.js，满足单文件
 * 有效行数门禁）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 列表页渲染 页签/筛选区/表格，"新增记录"入口与导出按钮在位；列表加载
 *   失败显式提示并可重试；
 * - 导出与已执行查询条件一致（2026-10-15）：关键词输入草稿不进导出参数与
 *   "导出范围"文案，查询提交后才生效；
 * - 跨页跳转 ?system= 预设所属系统筛选；
 * - 新增表单按记录类型显隐故障专用字段（设备故障显示影响开关/影响程度/
 *   故障部位/初步原因分析；一般记录/异常事件不渲染），并按类型提交真实
 *   payload（record_type + client_token）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

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
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement(
    'button',
    {
      onClick: props.onClick,
      'data-auth': props.auth || '',
      type: 'button',
    },
    props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = Shell;
  const SearchForm = (props) => React.createElement('div', null, props.children);
  // 与 Shell.Item 一致：渲染 title（筛选分层测试依赖标签文案）
  SearchForm.Item = Shell.Item;
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb,
    SearchForm,
    ExportButton: (props) => React.createElement('button', {
      type: 'button',
      'data-export-params': JSON.stringify(props.params || {}),
    }, props.children),
    TableCard: Shell,
    AttachmentManager: (props) => React.createElement(
      'div', {'data-object-type': props.objectType}, 'attachments'),
    // 列表附件列复用真实 AttachmentCountBadge（与无线电台执照同款样式）
    AttachmentCountBadge: jest.requireActual('components').AttachmentCountBadge,
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

let container = null;

// 重试按钮：antd 对两字中文按钮自动插空格（"重 试"），匹配前去掉空白
function findRetryButton() {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === '重试');
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  mockHttpPost.mockReset();
  mockHttpPost.mockResolvedValue({data: {}});
  mockHttpPut.mockReset();
  mockHttpPut.mockResolvedValue({data: {}});
  mockHttpDelete.mockReset();
  mockHttpDelete.mockResolvedValue({});
  // store 为模块级单例：跨测试重置可见性/失败标记/筛选草稿，避免上个用例的
  // 详情弹窗/失败横幅/关键词草稿泄入下个用例
  const store = require('../store').default;
  store.detailVisible = false;
  store.formVisible = false;
  store.detailId = null;
  store.detail = {};
  store.detailError = false;
  store.fetchError = false;
  store.todoError = false;
  store.statsError = false;
  store.systemRecordsError = false;
  store.records = [];
  store.todoRecords = [];
  store.todoCounts = null;
  store.statistics = null;
  store.pendingSection = 'basic';
  store.input_keyword = '';
  store.f_keyword = undefined;
  store.sf_input_keyword = '';
  store.sf_keyword = undefined;
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-select-dropdown, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function textContent() {
  return document.body.textContent || '';
}

function findButton(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').trim() === label);
}

// 两字中文按钮被 antd 自动插空格（"查 询"）：按去空白后的文本匹配
function findButtonNoSpace(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === label);
}

async function renderIndex() {
  const Index = require('../index').default;
  await act(async () => {
    ReactDOM.render(React.createElement(Index, {location: {search: ''}}), container);
  });
  await act(async () => {
    await flush();
  });
}

const FAULT_DETAIL = {
  id: 11, record_no: 'JL20261011-0001', record_type: 'fault',
  system: 3, system_name: 'DVOR系统', system_location: '机房A',
  occurred_at: '2026-10-11 08:00:00', title: '发射机故障',
  description: '告警灯亮', registrar_name: '张三', status: 'handling',
  affects_system_operation: true, impact_status: 'fault',
  reason_analysis: '', reason_unknown: false,
  source_type: 'manual', source_ledger: null, source_ledger_no: '',
  progress_count: 0, created_by_name: 'op_user',
  latest_progress_at: '2026-10-11 10:30:00', duration_seconds: 9000,
};

describe('运行处置记录列表页——附件列（2026-10-19）', () => {
  it('附件列区分 0、有效数量和缺失字段，数量直达附件区', async () => {
    mockHttpGet.mockImplementation(url => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
      if (url.endsWith('/attachments/')) return Promise.resolve([{id: 1}]);
      if (url.includes('/records/11/')) return Promise.resolve(FAULT_DETAIL);
      return Promise.resolve({data: [
        {...FAULT_DETAIL, attachment_count: 3},
        {...FAULT_DETAIL, id: 12, title: '空附件', attachment_count: 0},
        {...FAULT_DETAIL, id: 13, title: '计数异常'},
      ], total: 3});
    });
    await renderIndex();
    const rows = container.querySelectorAll('.ant-table-tbody .ant-table-row');
    // 数量样式与无线电台执照一致：公共 AttachmentCountBadge（📎+蓝色数字）
    expect(rows[0].querySelector('span[title="查看附件"] a').textContent).toContain('3');
    expect(rows[0].querySelector('span[title="查看附件"] .anticon-paper-clip')).toBeTruthy();
    expect(rows[1].textContent).toContain('-');
    expect(rows[1].querySelector('span[title="查看附件"]')).toBeNull();
    expect(rows[2].querySelector('[title="附件数量不可用"]').textContent).toBe('?');
    await act(async () => {
      rows[0].querySelector('span[title="查看附件"] a').dispatchEvent(
        new MouseEvent('click', {bubbles: true, cancelable: true}));
      await flush();
    });
    const store = require('../store').default;
    expect(store.attachmentsExpanded).toBe(true);
    expect(store.pendingSection).toBe('basic');
  });
});

describe('运行处置记录列表页', () => {
  it('渲染三个页签、筛选区与"新增记录"入口，列表请求统一路由', async () => {
    await renderIndex();
    const text = textContent();
    expect(text).toContain('全部记录');
    expect(text).toContain('待办（跟进中+处置中）');
    expect(text).toContain('统计');
    expect(text).toContain('新增记录');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/',
      expect.objectContaining({params: expect.objectContaining({page: 1})}));
  });

  it('列表渲染最近更新列；发生至最近进展只在详情展示，列表不出现', async () => {
    mockHttpGet.mockResolvedValue({data: [
      {id: 1, record_no: 'JL20261012-0001', record_type: 'routine',
        system_name: 'DVOR系统', title: 'UPS巡检', status: 'recorded',
        occurred_at: '2026-10-11 08:00:00', registrar_name: '张三',
        progress_count: 2, latest_progress_at: '2026-10-11 10:30:00',
        duration_seconds: 9000},
      {id: 2, record_no: 'JL20261012-0002', record_type: 'abnormal',
        system_name: 'DVOR系统', title: '信号波动', status: 'following_up',
        occurred_at: '2026-10-11 09:00:00', registrar_name: '张三',
        progress_count: 0, latest_progress_at: null, duration_seconds: null},
    ], total: 2});
    await renderIndex();
    const text = textContent();
    expect(text).toContain('最近更新');
    // 有进展：最新进展时间仍在列表展示（9000s=2.5h 的时长文本只允许在详情出现）
    expect(text).toContain('2026-10-11 10:30:00');
    expect(text).not.toContain('发生至最近进展');
    expect(text).not.toContain('2小时30分钟');
  });

  it('标题可直接打开详情；编号带复制入口（复制图标在位）', async () => {
    mockHttpGet.mockResolvedValue({data: [
      {id: 1, record_no: 'JL20261012-0001', record_type: 'routine',
        system_name: 'DVOR系统', title: 'UPS巡检', status: 'recorded',
        occurred_at: '2026-10-11 08:00:00', progress_count: 0},
    ], total: 1});
    await renderIndex();
    // 编号复制图标（antd Typography copyable）
    expect(document.querySelector('.ant-typography-copy')).toBeTruthy();
    // 标题链接点击 → showDetail → 拉取真实详情
    const titleLink = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === 'UPS巡检');
    expect(titleLink).toBeTruthy();
    await act(async () => {
      titleLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/records/1/');
  });

  it('筛选分层：高频条件常驻，记录类型/异常类别/发生时间收入"更多筛选"', async () => {
    await renderIndex();
    let text = textContent();
    expect(text).toContain('关键词');
    expect(text).toContain('所属系统');
    // 状态常驻；记录类型/异常类别默认折叠（发生时间为表头列名，不作折叠断言）
    expect(text).toContain('状态');
    expect(text).not.toContain('异常类别');
    const toggle = Array.from(container.querySelectorAll('a'))
      .find(a => (a.textContent || '').includes('更多筛选'));
    expect(toggle).toBeTruthy();
    await act(async () => {
      toggle.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    text = textContent();
    expect(text).toContain('记录类型');
    expect(text).toContain('异常类别');
    expect(text).toContain('发生时间');
    expect(text).toContain('收起筛选');
  });

  it('导出携带当前筛选参数并按已执行条件明确导出范围', async () => {
    const store = require('../store').default;
    store.f_record_type = 'fault';
    store.f_status = 'handling';
    await renderIndex();
    const exportButton = container.querySelector('[data-export-params]');
    const params = JSON.parse(exportButton.getAttribute('data-export-params'));
    expect(params).toMatchObject({record_type: 'fault', status: 'handling'});
    // 导出范围文案按已执行条件逐项说明（与导出参数同口径）
    expect(textContent()).toContain('导出范围：当前查询条件（');
    expect(textContent()).toContain('类型「设备故障」');
    expect(textContent()).toContain('状态「处置中」');
    // 无筛选时提示导出全部未撤销
    await act(async () => {
      store.resetFilter();
      await flush();
    });
    expect(textContent()).toContain('导出范围：全部未撤销记录');
  });

  it('列表加载失败显示警告横幅并提供重试，成功后横幅消失', async () => {
    mockHttpGet.mockRejectedValue('boom');
    await renderIndex();
    await act(async () => {
      await flush();
    });
    let text = textContent();
    expect(text).toContain('列表加载失败，以下可能为上次查询结果');
    const retry = findRetryButton();
    expect(retry).toBeTruthy();
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await act(async () => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(textContent()).not.toContain('列表加载失败，以下可能为上次查询结果');
  });
});

describe('运行处置记录列表页——跨页系统筛选（2026-10-15）', () => {
  it('?system= 预设所属系统筛选（系统档案页签跳入），首屏请求即带系统参数', async () => {
    const store = require('../store').default;
    try {
      const Index = require('../index').default;
      await act(async () => {
        ReactDOM.render(
          React.createElement(Index, {location: {search: '?system=3'}}), container);
      });
      await act(async () => {
        await flush();
      });
      // 首次列表请求即携带 system=3（先应用筛选再取数，不先拉全量再过滤）
      const recordsCall = mockHttpGet.mock.calls
        .find(([url]) => url === '/api/equipment-lifecycle/records/');
      expect(recordsCall[1].params).toMatchObject({system: 3, page: 1});
      expect(store.f_system).toBe(3);
    } finally {
      store.resetFilter();
    }
  });
});

describe('导出与已执行查询条件一致（2026-10-15）', () => {
  it('关键词输入未查询：导出参数与导出范围文案仍为已执行条件，查询后同步', async () => {
    await renderIndex();
    const store = require('../store').default;
    const keywordInput = container.querySelector('input.ant-input');
    const inputSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    // 输入并查询：关键词成为已执行条件
    await act(async () => {
      inputSetter.call(keywordInput, 'UPS');
      keywordInput.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    await act(async () => {
      findButtonNoSpace('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(store.f_keyword).toBe('UPS');
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/records/',
      expect.objectContaining({params: expect.objectContaining({keyword: 'UPS'})}));
    // 再输入新词但不查询：导出参数与文案仍为已执行条件（与表格所见一致）
    await act(async () => {
      inputSetter.call(keywordInput, '未查询新词');
      keywordInput.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    let params = JSON.parse(
      container.querySelector('[data-export-params]').getAttribute('data-export-params'));
    expect(params).toMatchObject({keyword: 'UPS'});
    expect(textContent()).toContain('关键词「UPS」');
    expect(textContent()).not.toContain('未查询新词');
    // 点击查询后：导出参数与文案同步为新词
    await act(async () => {
      findButtonNoSpace('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    params = JSON.parse(
      container.querySelector('[data-export-params]').getAttribute('data-export-params'));
    expect(params).toMatchObject({keyword: '未查询新词'});
    expect(textContent()).toContain('关键词「未查询新词」');
  });
});

describe('新增/编辑表单按记录类型显隐故障字段', () => {
  async function openForm(recordType) {
    await renderIndex();
    const store = require('../store').default;
    await act(async () => {
      store.showForm();
    });
    await act(async () => {
      await flush();
    });
    // 通过遍历 Radio 切换类型（受控组件 onChange 双通道）
    const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper'));
    const target = radios.find(r => r.textContent === recordType.label);
    await act(async () => {
      target.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
  }

  it('设备故障：渲染故障专用字段（开启影响开关后出现影响程度）', async () => {
    await openForm(RECORD_TYPE_OPTIONS.find(i => i.value === 'fault'));
    const text = textContent();
    expect(text).toContain('故障登记（设备故障专用）');
    expect(text).toContain('影响系统运行');
    expect(text).toContain('故障部位/设备');
    expect(text).toContain('初步原因分析');
    // 默认"部件故障但不影响系统运行"：影响程度在开关开启后才出现
    expect(text).not.toContain('系统影响程度');
    const switchButton = document.querySelector('.ant-switch');
    await act(async () => {
      switchButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(textContent()).toContain('系统影响程度');
  });

  it('一般记录：不渲染故障专用字段，显示记录类别', async () => {
    await openForm(RECORD_TYPE_OPTIONS.find(i => i.value === 'routine'));
    const text = textContent();
    expect(text).not.toContain('故障登记（设备故障专用）');
    expect(text).not.toContain('初步原因分析');
    expect(text).toContain('记录类别');
  });

  it('异常事件：不渲染故障专用字段，显示异常类别', async () => {
    await openForm(RECORD_TYPE_OPTIONS.find(i => i.value === 'abnormal'));
    const text = textContent();
    expect(text).not.toContain('故障登记（设备故障专用）');
    expect(text).toContain('异常类别');
  });

  it('编辑表单类型不可修改（禁用）且不渲染登记人', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockHttpGet.mockImplementation((url) => (
      url.endsWith('/records/candidate-systems/')
        ? Promise.resolve({data: []})
        : Promise.resolve({...FAULT_DETAIL})));
    await act(async () => {
      store.showForm({...FAULT_DETAIL});
    });
    await act(async () => {
      ReactDOM.render(React.createElement(RecordForm), container);
      await flush();
    });
    const radioInputs = Array.from(document.querySelectorAll('.ant-radio-input'));
    expect(radioInputs.length).toBeGreaterThan(0);
    expect(radioInputs.every(r => r.disabled)).toBe(true);
    expect(textContent()).not.toContain('登记人');
  });

  it('无 add_fault 权限时设备故障选项前置禁用（不让用户填完才被拒）', async () => {
    const libs = require('libs');
    libs.hasPermission.mockReturnValue(false);
    try {
      await openForm(RECORD_TYPE_OPTIONS.find(i => i.value === 'fault'));
      const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper'));
      const faultRadio = radios.find(r => r.textContent === '设备故障');
      expect(faultRadio.className).toContain('ant-radio-wrapper-disabled');
      // 点击禁用项无效：仍停留一般记录，故障专用字段不渲染
      expect(textContent()).not.toContain('故障登记（设备故障专用）');
      // 前置说明告知需要单独授权与替代路径
      expect(textContent()).toContain('operation_record.add_fault');
      // 选中类型的用途说明在选项下方展示
      expect(textContent()).toContain('常规作业与运行情况留痕');
    } finally {
      libs.hasPermission.mockReturnValue(true);
    }
  });
});


const RECORD_TYPE_OPTIONS = [
  {value: 'routine', label: '一般记录'},
  {value: 'abnormal', label: '异常事件'},
  {value: 'fault', label: '设备故障'},
];
