/**
 * 工作页签 Store 与路由元信息行为测试（2026-10-19 导航改造）。
 *
 * 真实执行 routeMeta（拍平/匹配/权限过滤/面包屑链）与 workTabStore
 * （开页去重、关闭激活邻页、固定工作台、URL 恢复、sessionStorage 持久化），
 * mock 点仅两处：routes 配置（小规模等价结构）与 libs（hasPermission 可控 +
 * history 记录 push 调用）。
 */
const mockHasPermission = jest.fn(() => true);
const mockHistoryPush = jest.fn();

jest.mock('libs', () => ({
  hasPermission: mockHasPermission,
  history: {
    push: mockHistoryPush,
    listen: jest.fn(() => () => {}),
    location: {pathname: '/home', search: ''},
  },
}));

jest.mock('../../routes', () => [
  {icon: 'home', title: '工作台', auth: 'dashboard.dashboard.view', path: '/home', component: 'Home'},
  {icon: 'el', title: '设备管理', auth: 'el.system.view|el.ledger.view', child: [
    {title: '系统档案', auth: 'el.system.view', path: '/el/systems', component: 'Systems'},
    {title: '维护台账', auth: 'el.ledger.view', child: [
      {title: '周月维护台账', auth: 'el.ledger.view', path: '/el/week-month-ledgers', component: 'W'},
    ]},
    // 兼容重定向：hideInTag 不应进入页签/面包屑
    {path: '/el/excel-ledgers', auth: 'el.ledger.view', component: 'Redirect', hideInTab: true},
  ]},
  {path: '/upgrade/workbench/:id', component: 'WB', tabTitle: '升级工作台', tabCrumbs: ['设备管理', '系统升级管理']},
  {path: '/announcement', component: 'AL', tabTitle: '系统公告'},
  {path: '/maintenance/data-quality', component: 'DQ', tabTitle: '数据质量巡检', tabCrumbs: ['运维管理']},
  {path: '/welcome/index', component: 'WI', hideInTab: true},
]);

const {flattenRoutes, getFlatRoutes, resolveRoute, crumbsFor, resetRoutesCache} = require('../routeMeta');
const {MAX_WORK_TABS} = require('../workTabStore');
const store = require('../workTabStore').default;

const HOME_TAB = {key: '/home', title: '工作台', url: '/home', closable: false, ts: expect.any(Number)};

function loc(pathname, search) {
  return {pathname, search: search || ''};
}

/** 播种当前登录会话的持久化页签（restore 仅恢复同一 token 会话的数据）。 */
function seedSession(tabs, token) {
  sessionStorage.setItem('token', token || 'tok-current');
  sessionStorage.setItem('spug.workTabs.session', token || 'tok-current');
  sessionStorage.setItem('spug.workTabs', JSON.stringify(tabs));
}

beforeEach(() => {
  sessionStorage.clear();
  jest.clearAllMocks();
  mockHasPermission.mockReturnValue(true);
  store.restore(loc('/home'));
});

describe('routeMeta：拍平路由与面包屑链', () => {
  it('菜单叶子路由标题与层级取自路由配置', () => {
    const routes = getFlatRoutes();
    const systems = routes.find(r => r.path === '/el/systems');
    const weekMonth = routes.find(r => r.path === '/el/week-month-ledgers');
    expect(systems.title).toBe('系统档案');
    expect(systems.crumbs).toEqual(['设备管理']);
    expect(weekMonth.title).toBe('周月维护台账');
    expect(weekMonth.crumbs).toEqual(['设备管理', '维护台账']);
  });

  it('隐藏路由通过 tabTitle/tabCrumbs 声明归属，hideInTab 不出现', () => {
    const paths = getFlatRoutes().map(r => r.path);
    expect(paths).toContain('/announcement');
    expect(paths).toContain('/maintenance/data-quality');
    expect(paths).toContain('/upgrade/workbench/:id');
    expect(paths).not.toContain('/el/excel-ledgers');
    expect(paths).not.toContain('/welcome/index');
    const dq = resolveRoute('/maintenance/data-quality');
    expect(dq.route.title).toBe('数据质量巡检');
    expect(dq.route.crumbs).toEqual(['运维管理']);
  });

  it('crumbsFor 生成含首页的完整面包屑；参数路由与未知路径分别处理', () => {
    expect(crumbsFor('/el/systems')).toEqual(['首页', '设备管理', '系统档案']);
    expect(crumbsFor('/upgrade/workbench/12')).toEqual(
      ['首页', '设备管理', '系统升级管理', '升级工作台']);
    expect(crumbsFor('/announcement')).toEqual(['首页', '系统公告']);
    expect(crumbsFor('/no/such/path')).toEqual(['首页']);
  });

  it('权限过滤与路由注册同口径：无权限路由不进页签也不进面包屑', () => {
    mockHasPermission.mockImplementation(code => !String(code).includes('el.system.view'));
    resetRoutesCache();
    try {
      const paths = getFlatRoutes().map(r => r.path);
      expect(paths).not.toContain('/el/systems');
      expect(crumbsFor('/el/systems')).toEqual(['首页']);
      // 无 dashboard 权限时固定工作台页签也不存在
      mockHasPermission.mockImplementation(code => !String(code).includes('dashboard'));
      resetRoutesCache();
      store.restore(loc('/el/systems'));
      expect(store.tabs.map(t => t.key)).toEqual(['/el/systems']);
      expect(store.tabs[0].closable).toBe(true);
    } finally {
      mockHasPermission.mockReturnValue(true);
      resetRoutesCache();
    }
  });
});

describe('workTabStore：开页、去重与关闭', () => {
  it('restore 后固定工作台页签置首且不可关闭', () => {
    expect(store.tabs[0]).toEqual(HOME_TAB);
    expect(store.activeKey).toBe('/home');
  });

  it('syncLocation 打开新页签并记录完整 URL（含查询参数）', () => {
    store.syncLocation(loc('/el/systems', '?detail=3'));
    expect(store.tabs.map(t => t.key)).toEqual(['/home', '/el/systems']);
    expect(store.activeKey).toBe('/el/systems');
    expect(store.tabs[1]).toEqual({key: '/el/systems', title: '系统档案', url: '/el/systems?detail=3', closable: true, ts: expect.any(Number)});
    // 持久化到 sessionStorage
    const saved = JSON.parse(sessionStorage.getItem('spug.workTabs'));
    expect(saved).toEqual([
      {key: '/home', url: '/home', ts: expect.any(Number)},
      {key: '/el/systems', url: '/el/systems?detail=3', ts: expect.any(Number)},
    ]);
  });

  it('同一路由不重复开页签，仅更新记住的 URL', () => {
    store.syncLocation(loc('/el/systems', '?detail=3'));
    store.syncLocation(loc('/el/systems', '?detail=5'));
    expect(store.tabs.filter(t => t.key === '/el/systems')).toHaveLength(1);
    expect(store.tabs.find(t => t.key === '/el/systems').url).toBe('/el/systems?detail=5');
  });

  it('hideInTab 重定向与未知路径不建立页签', () => {
    store.syncLocation(loc('/el/excel-ledgers', '?detail=1&source=excel'));
    store.syncLocation(loc('/no/such/path'));
    expect(store.tabs.map(t => t.key)).toEqual(['/home']);
    expect(store.activeKey).toBe('/home');
  });

  it('带参数路由按完整路径各占一个页签', () => {
    store.syncLocation(loc('/upgrade/workbench/12'));
    store.syncLocation(loc('/upgrade/workbench/13'));
    expect(store.tabs.map(t => t.title)).toEqual(['工作台', '升级工作台', '升级工作台']);
    expect(store.tabs.map(t => t.key)).toEqual(['/home', '/upgrade/workbench/12', '/upgrade/workbench/13']);
  });

  it('关闭激活页签后激活左侧邻页签并跳转其 URL', () => {
    store.syncLocation(loc('/el/systems'));
    store.syncLocation(loc('/el/week-month-ledgers'));
    expect(store.activeKey).toBe('/el/week-month-ledgers');
    store.closeTab('/el/week-month-ledgers');
    expect(store.tabs.map(t => t.key)).toEqual(['/home', '/el/systems']);
    expect(store.activeKey).toBe('/el/systems');
    expect(mockHistoryPush).toHaveBeenCalledWith('/el/systems');
  });

  it('关闭非激活页签不影响当前页签', () => {
    store.syncLocation(loc('/el/systems'));
    store.syncLocation(loc('/el/week-month-ledgers'));
    mockHistoryPush.mockClear();
    store.closeTab('/el/systems');
    expect(store.tabs.map(t => t.key)).toEqual(['/home', '/el/week-month-ledgers']);
    expect(store.activeKey).toBe('/el/week-month-ledgers');
    expect(mockHistoryPush).not.toHaveBeenCalled();
  });

  it('工作台页签拒绝关闭', () => {
    store.closeTab('/home');
    expect(store.tabs.map(t => t.key)).toContain('/home');
    expect(mockHistoryPush).not.toHaveBeenCalled();
  });

  it('关闭最后一个页签时回退到第一个有权限的菜单路由', () => {
    mockHasPermission.mockImplementation(code => !String(code).includes('dashboard'));
    resetRoutesCache();
    try {
      store.restore(loc('/el/systems'));
      expect(store.tabs.map(t => t.key)).toEqual(['/el/systems']);
      store.closeTab('/el/systems');
      expect(store.tabs).toHaveLength(0);
      expect(mockHistoryPush).toHaveBeenCalledWith('/el/systems');
    } finally {
      mockHasPermission.mockReturnValue(true);
      resetRoutesCache();
    }
  });
});

describe('workTabStore：刷新恢复与权限复核', () => {
  it('restore 按 sessionStorage 恢复页签并保留查询参数，剔除无权限与未知页签', () => {
    seedSession([
      {key: '/el/systems', url: '/el/systems?detail=3'},
      {key: '/el/excel-ledgers', url: '/el/excel-ledgers'},
      {key: '/no/such/path', url: '/no/such/path'},
      {key: '/announcement', url: '/announcement?keyword=公告'},
    ]);
    store.restore(loc('/el/systems', '?detail=3'));
    expect(store.tabs.map(t => t.key)).toEqual(['/home', '/el/systems', '/announcement']);
    expect(store.tabs[1].url).toBe('/el/systems?detail=3');
    expect(store.tabs[2].title).toBe('系统公告');
    expect(store.activeKey).toBe('/el/systems');
    expect(store.tabs[0].closable).toBe(false);
  });

  it('重复 restore 不会产生重复工作台页签，且重置滚动记忆', () => {
    store.syncLocation(loc('/el/systems'));
    store.scrollMemory['/el/systems'] = 320;
    store.restore(loc('/home'));
    expect(store.tabs.filter(t => t.key === '/home')).toHaveLength(1);
    expect(store.scrollMemory).toEqual({});
  });
});
