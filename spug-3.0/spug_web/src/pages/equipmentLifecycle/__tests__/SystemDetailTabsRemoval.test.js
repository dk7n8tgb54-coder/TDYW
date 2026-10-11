/**
 * 系统档案详情弹窗三页签下线（2026-10-11）前端契约测试。
 *
 * 真实渲染 SystemDetail（ReactDOM + jsdom，仓库惯例），验证：
 * - 详情弹窗不再包含"周月维护台账""季维护台账""系统履历"三个页签；
 * - 其余页签随 2026-10-11 合并改造收敛：基本信息 / 运行与故障记录 /
 *   升级记录 / 配置（原"故障记录""运行记录"两页签合并）；
 * - 页签专用组件 SystemLedgerTab / SystemEventsTab 已删除。
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
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement('span', null, props.children);
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb,
    SearchForm,
    ExportButton: AuthButton,
    TableCard: Shell,
  };
});

// jsdom 未实现 matchMedia，antd 渲染需要
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
  // 各页签挂载时的列表请求一律回空列表（本测试只断言页签结构）
  mockHttpGet.mockResolvedValue({data: [], total: 0});
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

describe('系统档案详情弹窗三页签下线', () => {
  it('详情弹窗不再包含 周月维护台账/季维护台账/系统履历 页签，其余页签保留', async () => {
    const store = require('../store').default;
    const SystemDetail = require('../SystemDetail').default;
    await act(async () => {
      store.showDetail({
        id: 5, name: 'DVOR 通信系统', system_model: 'VR-100',
        install_location: '机房A', health_status: 'normal',
        health_status_text: '正常', is_active: true,
      });
      ReactDOM.render(h(SystemDetail), container);
    });
    await act(async () => {});
    const labels = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .map(tab => tab.textContent);
    expect(labels).toEqual(
      expect.arrayContaining(['基本信息', '运行与故障记录', '升级记录', '配置']));
    ['周月维护台账', '季维护台账', '系统履历', '故障记录', '运行记录'].forEach(label => {
      expect(labels).not.toContain(label);
    });
  });

  it('页签专用组件 SystemLedgerTab / SystemEventsTab / FaultRecordsTab / SystemRuntimeRecordsTab 已整体删除', () => {
    [ '../ledger/SystemLedgerTab', '../systemEvent/SystemEventsTab',
      '../FaultRecordsTab', '../SystemRuntimeRecordsTab',
    ].forEach(modulePath => {
      let deleted = false;
      try {
        jest.isolateModules(() => require(modulePath));
      } catch (e) {
        deleted = true;
      }
      expect(deleted).toBe(true);
    });
  });
});
