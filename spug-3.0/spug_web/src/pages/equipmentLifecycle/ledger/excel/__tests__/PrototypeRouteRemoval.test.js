/**
 * 模板导入验证原型下线后的前端路由表行为测试（2026-10-01）。
 *
 * 真实加载 routes.js 路由表（完整模块图，不读源码做正则匹配）：
 * - /el/ledger-prototype 路由与「模板导入验证」菜单项不再存在；
 * - 正式 Excel 模板管理与周月/季维护台账路由仍然存在。
 */
const mockHistory = {location: {search: ''}, replace: jest.fn(), push: jest.fn()};

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  exportFile: jest.fn(),
  history: mockHistory,
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  X_TOKEN: '',
}));

const routes = require('../../../../../routes').default;

function collectPaths(entries, acc) {
  (entries || []).forEach(entry => {
    if (entry.path) acc.push({path: entry.path, title: entry.title});
    if (entry.child) collectPaths(entry.child, acc);
  });
  return acc;
}

describe('原型路由下线', () => {
  const all = collectPaths(routes, []);

  test('不再存在 /el/ledger-prototype 路由与「模板导入验证」菜单项', () => {
    expect(all.some(item => item.path === '/el/ledger-prototype')).toBe(false);
    expect(all.some(item => item.title === '模板导入验证')).toBe(false);
  });

  test('正式 Excel 路线路由仍然存在', () => {
    expect(all.some(item => item.path === '/el/excel-ledger-templates')).toBe(true);
    expect(all.some(item => item.path === '/el/week-month-ledgers')).toBe(true);
    expect(all.some(item => item.path === '/el/seasonal-ledgers')).toBe(true);
  });
});
