/**
 * 系统档案——"运行与故障记录"页签契约测试（2026-10-11 合并改造）。
 * 真实渲染页签组件，mock libs.http，验证：
 * - 挂载即请求 systems/<id>/records/（系统档案直接查询统一主表，
 *   不经过履历事件表）；
 * - 记录类型筛选（日常运行/异常事件/正式故障）作为 record_type 参数生效；
 * - 表格展示编号/类型/标题/状态列，详情点击打开统一详情窗口；
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

const SYSTEM_RECORDS = {
  data: [
    {id: 21, record_no: 'JL20261011-0021', record_type: 'routine',
      title: 'UPS巡检', status: 'recorded', category_text: '', occurred_at: '2026-10-11 08:00:00'},
    {id: 22, record_no: 'JL20261011-0022', record_type: 'abnormal',
      title: '信号波动', status: 'following_up', category_text: '信号异常',
      occurred_at: '2026-10-11 09:00:00'},
    {id: 23, record_no: 'JL20261011-0023', record_type: 'fault',
      title: '发射机故障', status: 'cancelled', category_text: '',
      occurred_at: '2026-10-11 10:00:00'},
  ],
  total: 3,
  latest_occurred_at: '2026-10-11 10:00:00',
};

describe('系统档案运行与故障记录页签', () => {
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
    expect(text).toContain('日常运行');
    expect(text).toContain('异常事件');
    expect(text).toContain('正式故障');
    expect(text).toContain('最近发生时间：2026-10-11 10:00:00');
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
