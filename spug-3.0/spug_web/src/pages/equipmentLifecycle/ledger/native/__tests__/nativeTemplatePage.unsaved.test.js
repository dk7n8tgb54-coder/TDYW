/**
 * 原生台账模板页未保存登记接线行为测试（2026-10-20）。
 *
 * 真实渲染 NativeTemplatePage（observer + 真实 nativeTemplateStore 单例 +
 * 真实 workTabStore/useWorkTabUnsaved），验证编辑器脏标记（editorDirty，
 * iframe 编辑内容不落盘、页签被自动关闭会丢失）变化时当前页签的未保存
 * 登记随之建立/撤销，卸载后不留残留。mock 点：libs（http/history）、
 * 公共组件壳、编辑器宿主（iframe/Univer 不在本次验证范围）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHistory = {
  push: jest.fn(),
  listen: jest.fn(() => () => {}),
  block: jest.fn(() => () => {}),
  location: {pathname: '/el/native-ledger-templates', search: ''},
};

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: mockHistory,
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = props => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell,
    AuthButton: props => React.createElement('span', {onClick: props.onClick}, props.children),
    AuthCard: Shell,
    AuthFragment: Shell,
  };
});

jest.mock('../NativeTemplateEditorHost', () => () => null);

jest.mock('../../../../../routes', () => [
  {icon: 'home', title: '工作台', auth: 'dashboard.dashboard.view', path: '/home', component: 'Home'},
  {title: '原生台账模板', auth: 'el.template.view', path: '/el/native-ledger-templates', component: 'NT'},
]);

const store = require('../nativeTemplateStore').default;
const workTabStore = require('../../../../../layout/workTabStore').default;
const NativeTemplatePage = require('../NativeTemplatePage').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  sessionStorage.clear();
  jest.clearAllMocks();
  mockHttpGet.mockResolvedValue({data: []});
  store.editorDirty = false;
  store.editing = false;
  store.detail = null;
  store.list = [];
  workTabStore.restore({pathname: mockHistory.location.pathname, search: ''});
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  container = null;
});

describe('NativeTemplatePage 编辑器未保存登记接线', () => {
  it('editorDirty 变化驱动页签未保存登记建立与撤销', async () => {
    await act(async () => {
      ReactDOM.render(<NativeTemplatePage/>, container);
      await flush();
    });
    expect(mockHttpGet).toHaveBeenCalled();
    expect(workTabStore.hasUnsaved('/el/native-ledger-templates')).toBe(false);
    // 编辑器推送脏标记：页签登记为有未保存内容
    await act(async () => {
      store.editorDirty = true;
      await flush();
    });
    expect(workTabStore.hasUnsaved('/el/native-ledger-templates')).toBe(true);
    // 保存/复位后撤销
    await act(async () => {
      store.editorDirty = false;
      await flush();
    });
    expect(workTabStore.hasUnsaved('/el/native-ledger-templates')).toBe(false);
  });

  it('页签关闭（组件卸载）后登记自动撤销', async () => {
    await act(async () => {
      ReactDOM.render(<NativeTemplatePage/>, container);
      await flush();
    });
    await act(async () => {
      store.editorDirty = true;
      await flush();
    });
    expect(workTabStore.hasUnsaved('/el/native-ledger-templates')).toBe(true);
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
      container = document.createElement('div');
      document.body.appendChild(container);
    });
    expect(workTabStore.hasUnsaved('/el/native-ledger-templates')).toBe(false);
  });
});
