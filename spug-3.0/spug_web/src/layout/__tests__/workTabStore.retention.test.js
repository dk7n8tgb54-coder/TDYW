/**
 * 工作页签数量上限、最近使用淘汰与未保存内容保护行为测试（2026-10-20）。
 *
 * 真实执行 workTabStore 的上限淘汰 / 最近使用记录 / 未保存登记 /
 * checkNavigation 准入检查 / 会话身份恢复，mock 点仅两处：routes 配置
 * （小规模等价结构）与 libs（hasPermission 可控 + history 记录 push）；
 * Date.now 用递增序列替换使"最近使用"可精确断言。
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
  {title: '页面A', auth: 'a.view', path: '/page-a', component: 'A'},
  {title: '页面B', auth: 'a.view', path: '/page-b', component: 'B'},
  {title: '页面C', auth: 'a.view', path: '/page-c', component: 'C'},
  {title: '页面D', auth: 'a.view', path: '/page-d', component: 'D'},
  {title: '页面E', auth: 'a.view', path: '/page-e', component: 'E'},
  {title: '页面F', auth: 'a.view', path: '/page-f', component: 'F'},
  {path: '/upgrade/workbench/:id', component: 'WB', tabTitle: '升级工作台'},
  {path: '/el/excel-ledgers', auth: 'a.view', component: 'Redirect', hideInTab: true},
]);

const store = require('../workTabStore').default;

function loc(pathname, search) {
  return {pathname, search: search || ''};
}

function closableKeys() {
  return store.tabs.filter(tab => tab.closable !== false).map(tab => tab.key);
}

/** 播种当前登录会话的持久化页签（restore 仅恢复同一 token 会话的数据）。 */
function seedSession(tabs, token) {
  sessionStorage.setItem('token', token || 'tok-current');
  sessionStorage.setItem('spug.workTabs.session', token || 'tok-current');
  sessionStorage.setItem('spug.workTabs', JSON.stringify(tabs));
}

let clock = 0;
let nowSpy = null;

beforeEach(() => {
  sessionStorage.clear();
  jest.clearAllMocks();
  mockHasPermission.mockReturnValue(true);
  clock = 1000;
  nowSpy = jest.spyOn(Date, 'now').mockImplementation(() => (clock += 1000));
  store.restore(loc('/home'));
});

afterEach(() => {
  nowSpy.mockRestore();
});

describe('数量上限与最近使用淘汰', () => {
  it('打开第 7 个页签时自动淘汰最久未使用的页签，再加入新页签', () => {
    ['/page-a', '/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
      path => store.syncLocation(loc(path)));
    expect(closableKeys()).toHaveLength(6);
    // 切回 A~E：其最近使用时间被刷新，从未回访的 F 最久未使用
    store.syncLocation(loc('/page-a'));
    store.syncLocation(loc('/page-b'));
    store.syncLocation(loc('/page-c'));
    store.syncLocation(loc('/page-d'));
    store.syncLocation(loc('/page-e'));
    store.syncLocation(loc('/upgrade/workbench/99'));
    expect(closableKeys()).toEqual([
      '/page-a', '/page-b', '/page-c', '/page-d', '/page-e',
      '/upgrade/workbench/99',
    ]);
  });

  it('固定工作台页签不参与淘汰，永远置首', () => {
    ['/page-a', '/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
      path => store.syncLocation(loc(path)));
    expect(store.tabs[0].key).toBe('/home');
    expect(store.tabs[0].closable).toBe(false);
    store.syncLocation(loc('/upgrade/workbench/99'));
    expect(store.tabs[0].key).toBe('/home');
    expect(closableKeys()).toHaveLength(6);
  });

  it('切换页签只刷新最近使用记录，不改变显示顺序', () => {
    store.syncLocation(loc('/page-a'));
    store.syncLocation(loc('/page-b'));
    store.syncLocation(loc('/page-c'));
    const tsB = store.tabs.find(tab => tab.key === '/page-b').ts;
    store.syncLocation(loc('/page-a'));
    expect(store.tabs.map(tab => tab.key)).toEqual(['/home', '/page-a', '/page-b', '/page-c']);
    const tsA = store.tabs.find(tab => tab.key === '/page-a').ts;
    const tsBAfter = store.tabs.find(tab => tab.key === '/page-b').ts;
    expect(tsA).toBeGreaterThan(tsBAfter);
    expect(tsBAfter).toBe(tsB);
  });

  it('自动淘汰时同步清理滚动记忆与持久化记录', () => {
    ['/page-a', '/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
      path => store.syncLocation(loc(path)));
    store.scrollMemory['/page-a'] = 320;
    store.syncLocation(loc('/upgrade/workbench/99'));
    // A 为最久未使用者：滚动记忆与 sessionStorage 记录一并清除
    expect(store.scrollMemory).not.toHaveProperty('/page-a');
    const saved = JSON.parse(sessionStorage.getItem('spug.workTabs'));
    expect(saved.map(item => item.key)).not.toContain('/page-a');
    expect(saved.filter(item => item.key !== '/home')).toHaveLength(6);
  });

  it('手动关闭页签同样清理滚动记忆与未保存登记', () => {
    store.syncLocation(loc('/page-a'));
    store.scrollMemory['/page-a'] = 480;
    const release = store.addUnsavedSource('/page-a');
    expect(store.hasUnsaved('/page-a')).toBe(true);
    store.closeTab('/page-a');
    expect(store.scrollMemory).not.toHaveProperty('/page-a');
    expect(store.hasUnsaved('/page-a')).toBe(false);
    release();
  });
});

describe('未保存内容保护', () => {
  it('有未保存内容的页签不被自动淘汰', () => {
    ['/page-a', '/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
      path => store.syncLocation(loc(path)));
    // F 最久未使用但已登记未保存内容：淘汰次久的 E
    store.addUnsavedSource('/page-f');
    ['/page-a', '/page-b', '/page-c', '/page-d'].forEach(
      path => store.syncLocation(loc(path)));
    store.syncLocation(loc('/upgrade/workbench/99'));
    expect(closableKeys()).toContain('/page-f');
    expect(closableKeys()).not.toContain('/page-e');
    expect(closableKeys()).toHaveLength(6);
  });

  it('同一页签多处未保存来源按计数合并，全部撤销才算无未保存', () => {
    expect(store.hasUnsaved('/page-a')).toBe(false);
    const release1 = store.addUnsavedSource('/page-a');
    const release2 = store.addUnsavedSource('/page-a');
    expect(store.hasUnsaved('/page-a')).toBe(true);
    release1();
    expect(store.hasUnsaved('/page-a')).toBe(true);
    release2();
    expect(store.hasUnsaved('/page-a')).toBe(false);
  });

  describe('checkNavigation 导航准入', () => {
    it('未达上限或目标为已开页签时放行', () => {
      store.syncLocation(loc('/page-a'));
      expect(store.checkNavigation('/page-b').allowed).toBe(true);
      expect(store.checkNavigation('/page-a').allowed).toBe(true);
      // 已达上限但目标为已开页签：放行
      ['/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
        path => store.syncLocation(loc(path)));
      expect(store.checkNavigation('/page-c').allowed).toBe(true);
    });

    it('已达上限但存在可淘汰页签时放行（淘汰由 syncLocation 执行）', () => {
      ['/page-a', '/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
        path => store.syncLocation(loc(path)));
      expect(store.checkNavigation('/upgrade/workbench/99')).toEqual({allowed: true});
    });

    it('全部候选页签均有未保存内容时阻止并给出提示文案', () => {
      ['/page-a', '/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
        path => store.syncLocation(loc(path)));
      const releases = closableKeys().map(key => store.addUnsavedSource(key));
      const verdict = store.checkNavigation('/upgrade/workbench/99');
      expect(verdict.allowed).toBe(false);
      expect(verdict.reason).toContain('未保存');
      expect(verdict.reason).toContain('6');
      // 释放页面 A 的登记后恢复放行
      releases[0]();
      expect(store.checkNavigation('/upgrade/workbench/99').allowed).toBe(true);
    });

    it('不建页签路径（重定向/未知）不做上限检查', () => {
      ['/page-a', '/page-b', '/page-c', '/page-d', '/page-e', '/page-f'].forEach(
        path => store.syncLocation(loc(path)));
      closableKeys().forEach(key => store.addUnsavedSource(key));
      expect(store.checkNavigation('/el/excel-ledgers').allowed).toBe(true);
      expect(store.checkNavigation('/no/such/path').allowed).toBe(true);
    });
  });
});

describe('刷新恢复与重新登录清理', () => {
  it('同一登录会话内刷新恢复已开页签并复核权限', () => {
    store.syncLocation(loc('/page-a', '?keyword=测试'));
    store.syncLocation(loc('/page-b'));
    seedSession(JSON.parse(sessionStorage.getItem('spug.workTabs')));
    store.restore(loc('/page-b'));
    expect(store.tabs.map(tab => tab.key)).toEqual(['/home', '/page-a', '/page-b']);
    expect(store.tabs.find(tab => tab.key === '/page-a').url).toBe('/page-a?keyword=测试');
    expect(store.activeKey).toBe('/page-b');
  });

  it('重新登录或切换账号（token 变化）后清空上次页签与最近使用记录', () => {
    store.syncLocation(loc('/page-a'));
    seedSession(JSON.parse(sessionStorage.getItem('spug.workTabs')), 'tok-old');
    sessionStorage.setItem('token', 'tok-new');
    store.restore(loc('/page-a'));
    expect(store.tabs.map(tab => tab.key)).toEqual(['/home', '/page-a']);
    expect(store.scrollMemory).toEqual({});
    // 清空后的会话身份标记已更新为当前 token
    expect(sessionStorage.getItem('spug.workTabs.session')).toBe('tok-new');
  });

  it('历史持久化数据超过上限时仅保留最近使用的页签', () => {
    seedSession([
      {key: '/page-a', url: '/page-a', ts: 100},
      {key: '/page-b', url: '/page-b', ts: 800},
      {key: '/page-c', url: '/page-c', ts: 300},
      {key: '/page-d', url: '/page-d', ts: 700},
      {key: '/page-e', url: '/page-e', ts: 600},
      {key: '/page-f', url: '/page-f', ts: 500},
      {key: '/page-c', url: '/page-c', ts: 900},
      {key: '/upgrade/workbench/1', url: '/upgrade/workbench/1', ts: 400},
      {key: '/upgrade/workbench/2', url: '/upgrade/workbench/2', ts: 200},
    ]);
    store.restore(loc('/page-b'));
    expect(closableKeys()).toHaveLength(6);
    // 保留 ts 最高的 6 条（重复 key 去重后取最近），ts 最低的 A 与 workbench/2 被截断
    expect(closableKeys()).not.toContain('/page-a');
    expect(closableKeys()).not.toContain('/upgrade/workbench/2');
    expect(closableKeys()).toEqual(
      ['/page-b', '/page-c', '/page-d', '/page-e', '/page-f', '/upgrade/workbench/1']);
  });

  it('restore 重置滚动记忆与未保存登记', () => {
    store.syncLocation(loc('/page-a'));
    store.scrollMemory['/page-a'] = 240;
    store.addUnsavedSource('/page-a');
    store.restore(loc('/page-a'));
    expect(store.scrollMemory).toEqual({});
    expect(store.hasUnsaved('/page-a')).toBe(false);
  });

  it('无工作台权限时按既有口径从合法默认入口开始', () => {
    mockHasPermission.mockImplementation(code => !String(code).includes('dashboard'));
    try {
      // restore 内部重置路由缓存，按当前权限重新过滤
      store.restore(loc('/page-a'));
      expect(store.tabs.map(tab => tab.key)).toEqual(['/page-a']);
      expect(store.tabs[0].closable).toBe(true);
    } finally {
      mockHasPermission.mockReturnValue(true);
    }
  });
});
