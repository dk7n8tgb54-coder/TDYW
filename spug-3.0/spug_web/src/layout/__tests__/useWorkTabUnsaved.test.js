/**
 * useWorkTabUnsaved hook 行为测试（2026-10-20）。
 *
 * 真实渲染探针组件执行 hook（登记 → 变化 → 撤销），配合真实 workTabStore，
 * 验证 dirty 声明与页签未保存登记的生命周期；libs 仅 mock history
 * （可指定当前 pathname）与 hasPermission。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHistory = {
  push: jest.fn(),
  listen: jest.fn(() => () => {}),
  block: jest.fn(() => () => {}),
  location: {pathname: '/el/week-month-ledgers', search: ''},
};

jest.mock('libs', () => ({
  hasPermission: jest.fn(() => true),
  history: mockHistory,
}));

jest.mock('../../routes', () => [
  {icon: 'home', title: '工作台', auth: 'dashboard.dashboard.view', path: '/home', component: 'Home'},
  {title: '周月维护台账', auth: 'el.ledger.view', path: '/el/week-month-ledgers', component: 'W'},
]);

const store = require('../workTabStore').default;
const useWorkTabUnsaved = require('../useWorkTabUnsaved').default;

let container = null;

function Probe({dirty}) {
  useWorkTabUnsaved(dirty);
  return null;
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  sessionStorage.clear();
  jest.clearAllMocks();
  store.restore({pathname: mockHistory.location.pathname, search: ''});
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  container = null;
});

describe('useWorkTabUnsaved 登记生命周期', () => {
  it('dirty 为真时登记当前页签，dirty 变假自动撤销', () => {
    act(() => {
      ReactDOM.render(<Probe dirty={false}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(false);
    act(() => {
      ReactDOM.render(<Probe dirty={true}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(true);
    act(() => {
      ReactDOM.render(<Probe dirty={false}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(false);
  });

  it('组件卸载时撤销登记，不留残留', () => {
    act(() => {
      ReactDOM.render(<Probe dirty={true}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(true);
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
      container = document.createElement('div');
      document.body.appendChild(container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(false);
  });

  it('多处来源（父页面与子视图）计数合并，互不冲突', () => {
    function DoubleProbe({dirtyA, dirtyB}) {
      useWorkTabUnsaved(dirtyA);
      useWorkTabUnsaved(dirtyB);
      return null;
    }
    act(() => {
      ReactDOM.render(<DoubleProbe dirtyA={true} dirtyB={false}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(true);
    act(() => {
      ReactDOM.render(<DoubleProbe dirtyA={true} dirtyB={true}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(true);
    act(() => {
      ReactDOM.render(<DoubleProbe dirtyA={false} dirtyB={true}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(true);
    act(() => {
      ReactDOM.render(<DoubleProbe dirtyA={false} dirtyB={false}/>, container);
    });
    expect(store.hasUnsaved('/el/week-month-ledgers')).toBe(false);
  });
});
