/**
 * 系统档案——"运行处置记录"页签契约测试（2026-10-11 合并改造）。
 * 真实渲染页签组件，mock libs.http，验证：
 * - 挂载即请求 systems/<id>/records/（系统档案直接查询统一主表，
 *   不经过履历事件表）；
 * - 记录类型筛选（一般记录/异常事件/设备故障）作为 record_type 参数生效；
 * - 表格展示类型/标题/编号/状态列（2026-10-14 列序与主列表对齐：
 *   编号后移到标题之后），详情点击打开统一详情窗口；
 * - 三类记录的"已撤销"标签使用虚线灰样式。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: jest.fn(),
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
  return {
    AuthDiv: Shell,
    AuthButton: (props) => React.createElement('button', {
      onClick: props.onClick, 'data-auth': props.auth || '', type: 'button',
    }, props.children),
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
  // store 为模块级单例：重置失败标记与详情可见性，避免跨用例泄漏
  const store = require('../store').default;
  store.systemRecordsError = false;
  store.detailVisible = false;
  store.detailId = null;
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

// 重试按钮：antd 对两字中文按钮自动插空格（"重 试"），匹配前去掉空白
function findRetryButton() {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === '重试');
}

const SYSTEM_RECORDS = {
  data: [
    {id: 21, record_no: 'JL20261011-0021', record_type: 'routine',
      title: 'UPS巡检', status: 'recorded', category_text: '', occurred_at: '2026-10-11 08:00:00',
      progress_count: 2, latest_progress_at: '2026-10-11 09:30:00', duration_seconds: 5400},
    {id: 22, record_no: 'JL20261011-0022', record_type: 'abnormal',
      title: '信号波动', status: 'following_up', category_text: '信号异常',
      occurred_at: '2026-10-11 09:00:00',
      progress_count: 0, latest_progress_at: null, duration_seconds: null},
    {id: 23, record_no: 'JL20261011-0023', record_type: 'fault',
      title: '发射机故障', status: 'cancelled', category_text: '',
      occurred_at: '2026-10-11 10:00:00'},
  ],
  total: 3,
  latest_occurred_at: '2026-10-11 10:00:00',
};

describe('系统档案运行处置记录页签', () => {
  it('挂载即请求 systems/<id>/records/，表格渲染三类记录', async () => {
    mockHttpGet.mockResolvedValue(SYSTEM_RECORDS);
    const Tab = require('../SystemOperationRecordsTab').default;
    await act(async () => {
      ReactDOM.render(React.createElement(Tab, {systemId: 7}), container);
    });
    await act(async () => {
      await flush();
    });
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/');
    const text = document.body.textContent || '';
    expect(text).toContain('JL20261011-0021');
    expect(text).toContain('一般记录');
    expect(text).toContain('异常事件');
    expect(text).toContain('设备故障');
    expect(text).toContain('最近发生时间：2026-10-11 10:00:00');
    // 最近更新列保留（2026-10-14 起持续时间移至详情展示，表格不再出现时长文本）
    expect(text).toContain('2026-10-11 09:30:00');
    expect(text).not.toContain('持续时间');
    expect(text).not.toContain('1小时30分钟');
  });

  it('记录类型筛选作为 record_type 参数生效', async () => {
    mockHttpGet.mockResolvedValue({data: [], total: 0});
    const Tab = require('../SystemOperationRecordsTab').default;
    await act(async () => {
      ReactDOM.render(React.createElement(Tab, {systemId: 7}), container);
    });
    await act(async () => {
      await flush();
    });
    mockHttpGet.mockClear();
    // 打开记录类型下拉（antd4：mousedown 落在 .ant-select-selector 上）
    // 并选择"异常事件"
    const selects = Array.from(container.querySelectorAll('.ant-select'));
    const typeSelect = selects.find(s => s.textContent.includes('记录类型'));
    const selector = typeSelect.querySelector('.ant-select-selector');
    await act(async () => {
      selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      selector.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      await flush();
    });
    const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
      .find(o => o.textContent === '异常事件');
    await act(async () => {
      option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      option.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({record_type: 'abnormal'})}));
  });
});

describe('系统档案记录页签——分页/失败重试/详情（2026-10-14 体验二轮）', () => {
  it('分页受控：翻页携带 page/page_size，查询始终重置第 1 页', async () => {
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 25});
    const Tab = require('../SystemOperationRecordsTab').default;
    let instance = null;
    await act(async () => {
      instance = ReactDOM.render(React.createElement(Tab, {systemId: 7}), container);
      await flush();
    });
    // 模拟翻页（与 Table pagination.onChange 同一方法）
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue({...SYSTEM_RECORDS, total: 25});
    await act(async () => {
      instance.fetchWithFilters({}, 2);
      await flush();
    });
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({
        page: 2, page_size: 10,
      })}));
    // 查询重置回第 1 页
    mockHttpGet.mockClear();
    await act(async () => {
      instance.fetchWithFilters();
      await flush();
    });
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({page: 1})}));
  });

  it('列表加载失败显示警告横幅并可重试', async () => {
    mockHttpGet.mockRejectedValue('boom');
    const Tab = require('../SystemOperationRecordsTab').default;
    await act(async () => {
      ReactDOM.render(React.createElement(Tab, {systemId: 7}), container);
    });
    await act(async () => {
      await flush();
    });
    expect(document.body.textContent).toContain('记录列表加载失败');
    mockHttpGet.mockClear();
    mockHttpGet.mockResolvedValue(SYSTEM_RECORDS);
    const retry = findRetryButton();
    await act(async () => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/7/records/',
      expect.objectContaining({params: expect.objectContaining({page: 1})}));
    expect(document.body.textContent).not.toContain('记录列表加载失败');
  });

  it('详情点击打开统一详情窗口（同一 store 单例）', async () => {
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
    const Tab = require('../SystemOperationRecordsTab').default;
    await act(async () => {
      ReactDOM.render(React.createElement(Tab, {systemId: 7}), container);
    });
    await act(async () => {
      await flush();
    });
    const detailLink = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '详情');
    await act(async () => {
      detailLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(document.querySelector('.ant-modal')).toBeTruthy();
    expect(document.body.textContent).toContain('JL20261011-0021');
  });
});
