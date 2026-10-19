/**
 * 实验室：原生维护台账样板内嵌页的行为测试。
 *
 * 真实加载 routes.js 路由表、角色权限树 codes.js 和页面组件：
 * - 菜单/路由使用独立权限码 lab.native_ledger.view；
 * - 权限树向角色管理暴露该权限；
 * - 有权限时渲染全屏 iframe，无权限时渲染 403。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHistory = {location: {search: ''}, replace: jest.fn(), push: jest.fn()};
const mockHasPermission = jest.fn(() => true);

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  exportFile: jest.fn(),
  history: mockHistory,
  hasPermission: mockHasPermission,
  Permission: {isSuper: true},
  X_TOKEN: '',
}));

const routes = require('../../../routes').default;
const codes = require('../../system/role/codes').default;
const NativeLedgerLab = require('../nativeLedger').default;

function collectPaths(entries, acc) {
  (entries || []).forEach(entry => {
    if (entry.path) acc.push({path: entry.path, title: entry.title, auth: entry.auth});
    if (entry.child) collectPaths(entry.child, acc);
  });
  return acc;
}

function renderLab() {
  const container = document.createElement('div');
  act(() => {
    ReactDOM.render(<NativeLedgerLab/>, container);
  });
  const html = container.innerHTML;
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  return html;
}

describe('实验室：原生维护台账', () => {
  test('菜单与路由使用 lab.native_ledger.view 权限', () => {
    const lab = routes.find(item => item.title === '实验室');
    expect(lab).toBeTruthy();
    expect(lab.auth).toBe('lab.native_ledger.view');
    const item = collectPaths(routes, []).find(entry => entry.path === '/lab/native-ledger');
    expect(item).toBeTruthy();
    expect(item.auth).toBe('lab.native_ledger.view');
  });

  test('角色权限树包含实验室/原生维护台账/查看', () => {
    const mod = codes.find(item => item.key === 'lab');
    expect(mod).toBeTruthy();
    const page = (mod.pages || []).find(item => item.key === 'native_ledger');
    expect(page).toBeTruthy();
    expect(page.perms.map(item => item.key)).toContain('view');
  });

  test('有权限时渲染全屏 iframe', () => {
    mockHasPermission.mockReturnValue(true);
    const html = renderLab();
    expect(html).toContain('<iframe');
    expect(html).toContain('/lab/native-ledger/index.html');
  });

  test('无权限时渲染 403', () => {
    mockHasPermission.mockReturnValue(false);
    const html = renderLab();
    expect(html).toContain('403');
    expect(html).not.toContain('<iframe');
  });
});
