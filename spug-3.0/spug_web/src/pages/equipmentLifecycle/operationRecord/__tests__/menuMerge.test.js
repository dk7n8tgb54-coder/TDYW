/**
 * 运行与故障记录——菜单/路由/权限树合并退役契约测试（2026-10-11 合并改造）。
 * 真实导入路由表与权限树，验证：
 * - 菜单只提供一个"运行与故障记录"入口（/el/records，
 *   equipment_lifecycle.operation_record.view），不再提供"故障处置"
 *   "运行记录""运行处置"分组与"系统履历"入口；
 * - 旧路由 /el/faults、/el/runtime-records、/el/system-events、
 *   /el/system-event-groups 全部注销；
 * - 旧页面模块（FaultIndex/FaultDetail/runtimeRecord/systemEvent 等）
 *   require 抛错（整体删除，无兼容层）；
 * - 角色权限树提供 operation_record 组且不再提供
 *   fault/runtime_record/system_event 组。
 */
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
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

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

describe('运行与故障记录菜单合并', () => {
  const routes = require('../../../../routes').default;
  const codes = require('../../../system/role/codes').default;

  it('设备管理分组只保留一个记录入口 /el/records', () => {
    const all = flattenRoutes(routes);
    const records = all.filter(r => r.path === '/el/records');
    expect(records.length).toBe(1);
    expect(records[0].title).toBe('运行与故障记录');
    expect(records[0].auth).toBe('equipment_lifecycle.operation_record.view');
    // 分组标题与权限串
    const group = routes.find(r => r.title === '设备管理');
    expect(group.auth).toContain('equipment_lifecycle.operation_record.view');
    expect(group.auth).not.toContain('equipment_lifecycle.fault.');
    expect(group.auth).not.toContain('equipment_lifecycle.runtime_record.');
    expect(group.auth).not.toContain('equipment_lifecycle.system_event.');
    // 旧菜单标题不再出现
    const titles = all.map(r => r.title);
    expect(titles).not.toContain('故障处置');
    expect(titles).not.toContain('运行记录');
    expect(titles).not.toContain('运行处置');
    expect(titles).not.toContain('系统履历');
  });

  it('旧路径路由全部注销', () => {
    const paths = flattenRoutes(routes).map(r => r.path);
    ['/el/faults', '/el/runtime-records', '/el/system-events',
      '/el/system-event-groups'].forEach(path => {
      expect(paths).not.toContain(path);
    });
  });

  it('旧页面模块已整体删除', () => {
    ['../FaultIndex', '../FaultForm', '../FaultDetail', '../faultStore',
      '../FaultRecordsTab', '../SystemRuntimeRecordsTab', '../FaultStatusTag',
      '../../runtimeRecord', '../../systemEvent',
    ].forEach(expectModuleDeleted);
  });

  it('角色权限树提供 operation_record 组，旧三组权限码退役', () => {
    const elGroup = codes.find(g => g.key === 'equipment_lifecycle');
    const pageKeys = elGroup.pages.map(p => p.key);
    expect(pageKeys).toContain('operation_record');
    expect(pageKeys).not.toContain('fault');
    expect(pageKeys).not.toContain('runtime_record');
    expect(pageKeys).not.toContain('system_event');
    const opGroup = elGroup.pages.find(p => p.key === 'operation_record');
    const actions = opGroup.perms.map(p => p.key);
    // 三种记录类型的核心动作权限齐备
    ['view', 'add', 'add_fault', 'edit', 'progress', 'complete',
      'identify_fault', 'recover', 'close', 'cancel', 'del', 'export',
    ].forEach(key => expect(actions).toContain(key));
  });
});
