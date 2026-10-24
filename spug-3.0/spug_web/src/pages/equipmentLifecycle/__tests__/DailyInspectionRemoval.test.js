/**
 * 日巡视（值班巡检）活跃功能下线（2026-10-11）前端契约测试。
 *
 * 真实导入路由表、模块与权限树（仓库惯例：ReactDOM + jsdom），验证：
 * - routes.js 不再注册日巡视（巡检中心）及其旧独立路径兼容路由，
 *   菜单中不再出现"日巡视"；
 * - "巡视与维护"菜单已更名"维护台账"，仅保留周月/季维护台账与
 *   Excel台账模板子项，权限串不再包含巡检权限码；
 * - 巡检页面/Store/常量与巡检中心外壳模块已整体删除（require 抛错）；
 * - 角色权限树不再提供 值班巡检/巡检模板 权限组；
 * - 旧巡检台账（历史）兼容保护不受影响（由 ledger/__tests__/
 *   LegacyInspectionRemoval.test.js 继续覆盖）。
 */
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

function flattenRoutes(nodes, acc = []) {
  (nodes || []).forEach(node => {
    acc.push(node);
    if (node.child) flattenRoutes(node.child, acc);
  });
  return acc;
}

function expectModuleDeleted(modulePath) {
  let deleted = false;
  try {
    jest.isolateModules(() => require(modulePath));
  } catch (e) {
    deleted = true;
  }
  expect(deleted).toBe(true);
}

describe('日巡视活跃功能下线', () => {
  const routes = require('../../../routes').default;
  const entries = require('../ledger/entries');
  const codes = require('../../system/role/codes').default;

  it('routes.js 不再注册日巡视（巡检中心）与旧巡检独立路径路由', () => {
    const all = flattenRoutes(routes);
    ['/el/inspection-center', '/el/inspection-today',
      '/el/inspection-sheets', '/el/inspection-templates',
    ].forEach(path => expect(all.some(r => r.path === path)).toBe(false));
    expect(all.some(r => r.title === '日巡视')).toBe(false);
  });

  it('菜单"巡视与维护"已更名"维护台账"，仅保留台账子项与权限', () => {
    const all = flattenRoutes(routes);
    const menu = all.find(r => r.title === '维护台账');
    expect(menu).toBeTruthy();
    // 权限串收窄：巡检权限码退役，只保留台账权限
    expect(menu.auth).not.toContain('inspection');
    expect(menu.auth).toBe(
      'equipment_lifecycle.ledger.view|equipment_lifecycle.ledger_template.view');
    const titles = (menu.child || []).map(r => r.title).filter(Boolean);
    // 原生台账模板菜单已随原生路线整体下线删除（2026-10-20）；
    // 数字表单模板菜单随数字表单路线接入（2026-10-21，与 Excel 模板并列）
    expect(titles).toEqual(
      ['周月维护台账', '季维护台账', 'Excel台账模板', '数字表单模板']);
  });

  it('顶层"设备管理"权限串不再包含巡检权限码', () => {
    const top = routes.find(r => r.title === '设备管理');
    expect(top).toBeTruthy();
    expect(top.auth).not.toContain('inspection');
  });

  it('巡检页面/Store/常量与巡检中心模块已整体删除', () => {
    expectModuleDeleted('../inspection/InspectionWorksheet');
    expectModuleDeleted('../inspection/SheetIndex');
    expectModuleDeleted('../inspection/TemplateIndex');
    expectModuleDeleted('../inspection/TemplateForm');
    expectModuleDeleted('../inspection/WorksheetCards');
    expectModuleDeleted('../inspection/DutyRangeExportModal');
    expectModuleDeleted('../inspection/store');
    expectModuleDeleted('../inspection/constants');
    expectModuleDeleted('../inspection/tableUtils');
    expectModuleDeleted('../inspectionCenter/index');
    expectModuleDeleted('../inspectionCenter/LegacyRedirect');
  });

  it('ledger/entries 不再导出任何巡检入口', () => {
    expect(entries.InspectionToday).toBeUndefined();
    expect(entries.InspectionTemplateIndex).toBeUndefined();
    expect(entries.InspectionSheetIndex).toBeUndefined();
  });

  it('角色权限树不再提供 值班巡检/巡检模板 权限组', () => {
    const elGroup = codes.find(g => g.key === 'equipment_lifecycle');
    expect(elGroup).toBeTruthy();
    const keys = elGroup.pages.map(p => p.key);
    expect(keys).not.toContain('inspection');
    expect(keys).not.toContain('inspection_template');
    // 台账权限组保留（维护台账与 Excel 台账模板仍需要）
    expect(keys).toContain('ledger');
    expect(keys).toContain('ledger_template');
  });
});
