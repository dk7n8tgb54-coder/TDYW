/**
 * 系统档案——"运行处置记录"页签契约测试（2026-10-11 合并改造，
 * 2026-10-15 体验三轮重构）。
 * 真实渲染页签组件，mock libs.http，验证：
 * - 挂载即以当前系统第 1 页请求 systems/<id>/records/（系统档案直接查询
 *   统一主表，不经过履历事件表）；
 * - 统一列呈现与主列表一致：标题为主要入口（前置类型标签，点击打开统一
 *   详情）、编号一键复制、故障影响并入状态列、进展数直达详情进展页签；
 *   不再保留重复的"详情"操作列；
 * - 筛选与主列表同构：关键词/状态常驻，记录类型/异常类别/发生时间收入
 *   "更多筛选"；状态变更即带参刷新（重置回第 1 页）；
 * - 查询/重置/翻页/失败重试同一组筛选条件（条件收进 store）；
 * - 空态区分"当前系统暂无记录"与"筛选后没有匹配记录"；
 * - "查看该系统全部记录"跳入主列表并自动携带 ?system=；
 * - 详情内状态动作成功后页签在位时以同组条件联动刷新，卸载后不再请求；
 * - 关键词输入草稿与已执行条件分离（2026-10-15）：状态等筛选变更即刷新但
 *   不代提交未执行的草稿，查询按钮提交草稿（与主列表同口径）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: jest.fn(),
    delete: jest.fn(),
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
  const SearchForm = (props) => React.createElement('div', null, props.children);
  // 与 Shell.Item 一致：渲染 title（筛选分层测试依赖标签文案）
  SearchForm.Item = (props) => React.createElement(
    'div', null, props.title || '', props.children);
  return {
    AuthDiv: Shell,
    AuthButton: (props) => React.createElement('button', {
      onClick: props.onClick, 'data-auth': props.auth || '', type: 'button',
    }, props.children),
    SearchForm,
    AttachmentManager: (props) => React.createElement(
      'div', {'data-object-type': props.objectType}, 'attachments'),
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

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  mockHttpPost.mockReset();
  mockHttpPost.mockResolvedValue({});
  // store 为模块级单例：重置页签筛选/失败标记/详情可见性，避免跨用例泄漏
  const store = require('../store').default;
  store.systemRecordsError = false;
  store.detailVisible = false;
  store.detailId = null;
  store.detail = {};
  store.activeTab = 'basic';
  store.systemRecords = [];
  store.systemRecordsTotal = 0;
  store.systemLatestOccurredAt = null;
  store.systemRecordsSystemId = null;
  store.systemRecordsPage = 1;
  store.sf_input_keyword = '';
  store.sf_keyword = undefined;
  store.sf_status = undefined;
  store.sf_category = undefined;
  store.sf_record_type = undefined;
  store.sf_occurred_range = undefined;
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-select-dropdown').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function textContent() {
  return document.body.textContent || '';
}

// antd 对两字中文按钮自动插空格（"重 试"），匹配前去掉空白
function findButton(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === label);
}

async function renderTab(systemId = 7) {
  const Tab = require('../SystemOperationRecordsTab').default;
  await act(async () => {
    ReactDOM.render(React.createElement(Tab, {systemId}), container);
  });
  await act(async () => {
    await flush();
  });
  return Tab;
}

// SearchForm.Item mock 渲染 <div>{title}{children}</div>：
// 按标签文本（首个子节点为纯文本且等于标签）定位表单项
function findItemByLabel(label) {
  return Array.from(container.querySelectorAll('div'))
    .find(d => d.firstChild && d.firstChild.nodeType === Node.TEXT_NODE
      && d.firstChild.textContent === label);
}

// 打开指定表单项的 Select 并选择选项（antd4：mousedown 落在
// .ant-select-selector 上，选项渲染在 body 上的 dropdown 中）
async function pickOption(label, optionText) {
  const selector = findItemByLabel(label).querySelector('.ant-select-selector');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    selector.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    await flush();
  });
  const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
    .find(o => o.textContent === optionText);
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

const SYSTEM_RECORDS = {
  data: [
    {id: 21, record_no: 'JL20261011-0021', record_type: 'routine',
      title: 'UPS巡检', status: 'recorded', category_text: '',
      occurred_at: '2026-10-11 08:00:00',
      progress_count: 2, latest_progress_at: '2026-10-11 09:30:00'},
    {id: 22, record_no: 'JL20261011-0022', record_type: 'abnormal',
      title: '信号波动', status: 'following_up', category_text: '信号异常',
      occurred_at: '2026-10-11 09:00:00',
      progress_count: 0, latest_progress_at: null},
    {id: 23, record_no: 'JL20261011-0023', record_type: 'fault',
      title: '发射机故障', status: 'cancelled', category_text: '',
      occurred_at: '2026-10-11 10:00:00', progress_count: 1},
    {id: 24, record_no: 'JL20261011-0024', record_type: 'fault',
      title: '电源模块故障', status: 'handling', category_text: '',
      occurred_at: '2026-10-11 11:00:00',
      affects_system_operation: true, impact_status: 'degraded',
      progress_count: 3},
    {id: 25, record_no: 'JL20261011-0025', record_type: 'fault',
      title: '板卡故障', status: 'handling', category_text: '',
      occurred_at: '2026-10-11 12:00:00',
      affects_system_operation: false, progress_count: 1},
  ],
  total: 5,
  latest_occurred_at: '2026-10-11 12:00:00',
};

describe('系统档案运行处置记录页签——统一列呈现（2026-10-15）', () => {
  it('挂载即以第 1 页请求，渲染标题入口/编号复制/状态+影响/进展数，无"详情"操作列', async () => {
    mockHttpGet.mockResolvedValue(SYSTEM_RECORDS);
    await renderTab();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        page: 1, page_size: 10,
      })}));
    const text = textContent();
    // 标题列前置类型标签（三类记录均渲染）
    expect(text).toContain('UPS巡检');
    expect(text).toContain('一般记录');
    expect(text).toContain('异常事件');
    expect(text).toContain('设备故障');
    // 故障影响并入状态列：影响运行显示程度标签，否则中性"不影响运行"
    expect(text).toContain('降级');
    expect(text).toContain('不影响运行');
    // 已撤销标签保留
    expect(text).toContain('已撤销');
    // 编号一键复制入口
    expect(document.querySelector('.ant-typography-copy')).toBeTruthy();
    // 进展数可点击（直达进展页签）
    expect(text).toContain('2 条');
    // 系统维度摘要与跳转入口
    expect(text).toContain('最近发生时间：2026-10-11 12:00:00');
    expect(text).toContain('查看该系统全部记录');
    // 不再保留重复的"详情"操作列（标题即入口）
    const detailLinks = Array.from(container.querySelectorAll('a'))
      .filter(a => (a.textContent || '').trim() === '详情');
    expect(detailLinks).toHaveLength(0);
    // 持续时间在详情展示，列表不出现
    expect(text).not.toContain('持续时间');
  });

  it('点击标题打开统一详情窗口（同一 store 单例）', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({data: [], total: 0});
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      if (url.includes('/records/21/')) {
        return Promise.resolve({
          id: 21, record_no: 'JL20261011-0021', record_type: 'routine',
          system_name: 'DVOR系统', status: 'recorded', title: 'UPS巡检',
          description: '巡检正常', source_type: 'manual',
        });
      }
      return Promise.resolve(SYSTEM_RECORDS);
    });
    await renderTab();
    const titleLink = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === 'UPS巡检');
    await act(async () => {
      titleLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(document.querySelector('.ant-modal')).toBeTruthy();
    expect(textContent()).toContain('JL20261011-0021');
  });

  it('进展数点击直达详情进展页签', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) {
        return Promise.resolve({data: [], total: 2});
      }
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      if (url.includes('/records/21/')) {
        return Promise.resolve({
          id: 21, record_no: 'JL20261011-0021', record_type: 'routine',
          system_name: 'DVOR系统', status: 'recorded', title: 'UPS巡检',
          description: '巡检正常', source_type: 'manual',
        });
      }
      return Promise.resolve(SYSTEM_RECORDS);
    });
    await renderTab();
    const store = require('../store').default;
    const countLink = Array.from(container.querySelectorAll('a'))
      .find(a => (a.textContent || '').trim() === '2 条');
    await act(async () => {
      countLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(document.querySelector('.ant-modal')).toBeTruthy();
    expect(store.activeTab).toBe('progress');
    // 进展页签为当前激活页签（一般记录=补充记录）
    const activeTab = document.querySelector('.ant-tabs-tab-active');
    expect(activeTab.textContent).toContain('补充记录');
  });
});

describe('系统档案记录页签——筛选分层与同组条件（2026-10-15）', () => {
  it('关键词/状态常驻，记录类型/异常类别/发生时间收入"更多筛选"', async () => {
    await renderTab();
    let text = textContent();
    expect(text).toContain('关键词');
    expect(text).toContain('状态');
    expect(text).not.toContain('异常类别');
    // 系统由档案固定：不出现系统选择器
    expect(text).not.toContain('所属系统');
    const toggle = Array.from(container.querySelectorAll('a'))
      .find(a => (a.textContent || '').includes('更多筛选'));
    await act(async () => {
      toggle.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    text = textContent();
    expect(text).toContain('记录类型');
    expect(text).toContain('异常类别');
    expect(text).toContain('收起筛选');
  });

  it('状态筛选变更即带参刷新并重置回第 1 页', async () => {
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 25});
    await renderTab();
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 25});
    await pickOption('状态', '已关闭');
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        status: 'closed', page: 1, page_size: 10,
      })}));
  });

  it('展开更多筛选后记录类型生效；折叠时提示仍生效的条件数', async () => {
    await renderTab();
    // 先在展开态选择记录类型=异常事件
    const toggle = Array.from(container.querySelectorAll('a'))
      .find(a => (a.textContent || '').includes('更多筛选'));
    await act(async () => {
      toggle.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    await pickOption('记录类型', '异常事件');
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        record_type: 'abnormal', page: 1,
      })}));
    // 折叠后入口提示 1 个仍生效的条件（记录类型）
    const collapse = Array.from(container.querySelectorAll('a'))
      .find(a => (a.textContent || '').includes('收起筛选'));
    await act(async () => {
      collapse.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const toggleAgain = Array.from(container.querySelectorAll('a'))
      .find(a => (a.textContent || '').includes('更多筛选'));
    expect(toggleAgain.textContent).toContain('（1）');
  });
});

describe('系统档案记录页签——同一组条件贯穿查询/重置/翻页/重试（2026-10-15）', () => {
  it('查询/重置/翻页/失败重试同一组筛选条件', async () => {
    const store = require('../store').default;
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 25});
    await renderTab();
    // 关键词经草稿提交为已执行条件（查询按钮），状态为直接生效条件
    store.setSystemKeywordInput('UPS');
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    store.sf_status = 'handling';
    // 翻页携带同组条件
    mockHttpGet.mockClear();
    await act(async () => {
      store.fetchSystemRecords(7, 2);
      await flush();
    });
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        page: 2, keyword: 'UPS', status: 'handling',
      })}));
    // 查询重置回第 1 页且条件不变
    mockHttpGet.mockClear();
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        page: 1, keyword: 'UPS', status: 'handling',
      })}));
    // 失败显式提示；重试沿用同一组条件与页码
    mockHttpGet.mockClear();
    mockHttpGet.mockRejectedValueOnce('boom');
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(textContent()).toContain('记录列表加载失败');
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 25});
    await act(async () => {
      findButton('重试').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        page: 1, keyword: 'UPS', status: 'handling',
      })}));
    expect(textContent()).not.toContain('记录列表加载失败');
    // 重置清空全部条件（含关键词草稿）
    mockHttpGet.mockClear();
    await act(async () => {
      findButton('重置').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: {page: 1, page_size: 10}}));
    expect(store.sf_keyword).toBeUndefined();
    expect(store.sf_input_keyword).toBe('');
  });
});

describe('系统档案记录页签——关键词草稿与已执行条件分离（2026-10-15）', () => {
  it('输入未查询不进查询：状态筛选联动只用已执行条件，查询按钮提交草稿', async () => {
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 25});
    await renderTab();
    const store = require('../store').default;
    const keywordInput = findItemByLabel('关键词').querySelector('input');
    const inputSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    await act(async () => {
      inputSetter.call(keywordInput, 'UPS');
      keywordInput.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    expect(store.sf_input_keyword).toBe('UPS');
    expect(store.sf_keyword).toBeUndefined();
    // 输入未查询：改状态触发联动刷新，请求不带未执行关键词
    mockHttpGet.mockClear();
    await pickOption('状态', '处置中');
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: {page: 1, page_size: 10, status: 'handling'}}));
    // 查询提交草稿：关键词与状态同时生效
    mockHttpGet.mockClear();
    await act(async () => {
      findButton('查询').dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(store.sf_keyword).toBe('UPS');
    expect(mockHttpGet).toHaveBeenLastCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: {
        page: 1, page_size: 10, status: 'handling', keyword: 'UPS'}}));
  });
});

describe('系统档案记录页签——空态/跳转/联动刷新（2026-10-15）', () => {
  it('空态三分支：决策函数区分加载失败/系统无记录/筛选后无匹配，占位行真实渲染', async () => {
    // 说明：jsdom 无布局测量（rc-table componentWidth=0）会隐藏空态文案，
    // 故文案分支以导出的决策函数验证（真实代码路径），占位行以真实渲染
    // 验证；空态文案的视觉呈现由 Playwright 真机走查确认
    const {systemTabEmptyMessage} = require('../SystemOperationRecordsTab');
    expect(systemTabEmptyMessage(true, true)).toBe('记录列表加载失败');
    expect(systemTabEmptyMessage(true, false)).toBe('记录列表加载失败');
    expect(systemTabEmptyMessage(false, true)).toBe('没有符合条件的记录');
    expect(systemTabEmptyMessage(false, false)).toBe('当前系统暂无记录');
    // 真实渲染：空数据且无筛选 → 空态占位行在位
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    await renderTab();
    expect(document.querySelector('.ant-table-placeholder')).toBeTruthy();
    const store = require('../store').default;
    expect(store.systemHasActiveFilter).toBe(false);
    // 设置筛选后（决策函数输入变化）：占位行仍在位
    store.sf_keyword = '不存在';
    mockHttpGet.mockClear();
    await act(async () => {
      store.fetchSystemRecords();
      await flush();
    });
    expect(document.querySelector('.ant-table-placeholder')).toBeTruthy();
    expect(store.systemHasActiveFilter).toBe(true);
  });

  it('"查看该系统全部记录"跳入主列表并自动携带系统筛选', async () => {
    await renderTab();
    const link = Array.from(container.querySelectorAll('a'))
      .find(a => (a.textContent || '').includes('查看该系统全部记录'));
    await act(async () => {
      link.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const {history} = require('libs');
    expect(history.push).toHaveBeenCalledWith('/el/records?system=7');
  });

  it('详情状态动作成功后页签在位时以同组条件联动刷新', async () => {
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 5});
    await renderTab();
    const store = require('../store').default;
    store.sf_status = 'handling';
    mockHttpGet.mockClear();
    // 模拟详情内完成跟进动作（真实调用 store 动作链）
    store.detailId = 24;
    await act(async () => {
      store.completeFollowUp({});
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/24/complete/', {});
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        status: 'handling', page: 1,
      })}));
  });

  it('卸载清空在位标记：此后联动刷新不再请求，详情窗口收起', async () => {
    mockHttpGet.mockResolvedValue(SYSTEM_RECORDS);
    await renderTab();
    const store = require('../store').default;
    // 打开详情后卸载（关闭系统详情场景）
    await act(async () => {
      store.showDetail(21);
      await flush();
    });
    expect(store.detailVisible).toBe(true);
    await act(async () => {
      ReactDOM.unmountComponentAtNode(container);
      await flush();
    });
    expect(store.detailVisible).toBe(false);
    expect(store.systemRecordsSystemId).toBe(null);
    mockHttpGet.mockClear();
    await store.refreshSystemRecordsIfActive();
    expect(mockHttpGet).not.toHaveBeenCalled();
  });
});
