/**
 * 低频到期菜单红点 Store 生命周期行为测试（2026-09 第二轮）。
 *
 * 对三个具体 Store（执照/批复/合同）执行同一组真实行为场景：
 * 真实实例化 Store 单例（jest.resetModules 后 require），mock libs，
 * 直接派发 window focus 与 document visibilitychange 事件、注入模拟
 * 本地自然日，验证事件驱动刷新生命周期：
 *
 * - start()：有权限立即请求一次；无权限不请求、不注册监听器
 * - 无固定轮询：推进计时器不产生新请求
 * - 同一自然日 focus / visible 不重复请求
 * - 跨自然日 focus / visible 各触发一次请求
 * - visibilityState 非 visible 不请求
 * - focus 与 visibilitychange 连续触发不产生并发双请求（在途去重）
 * - 请求失败不更新最后成功日期、保留旧数字、后续事件可重试
 * - 重复 start() / stop() 幂等
 * - fetch() 返回 Promise；无权限时不发请求
 */
const STORE_CONFIGS = [
  {
    name: '无线电台执照 Badge Store',
    module: '../RadioLicenseBadgeStore',
    perm: 'radio_license.license.view',
    url: '/api/radio-license/badge/',
  },
  {
    name: '台站频率批复 Badge Store',
    module: '../ApprovalBadgeStore',
    perm: 'radio_license.approval.view',
    url: '/api/radio-license/approvals/badge/',
  },
  {
    name: '合同协议 Badge Store',
    module: '../ContractAgreementBadgeStore',
    perm: 'contract_agreement.agreement.view',
    url: '/api/contract-agreement/badge/',
  },
];

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

// 模拟"当前本地自然日"（YYYY-MM-DD），各测试用 setToday 切换
let today = '2026-09-18';
const setToday = s => {
  today = s;
};

function freshStore(modulePath) {
  jest.resetModules();
  return require(modulePath).default;
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function fireFocus() {
  window.dispatchEvent(new Event('focus'));
}

function fireVisibility(state) {
  Object.defineProperty(document, 'visibilityState', {
    value: state,
    configurable: true,
  });
  document.dispatchEvent(new Event('visibilitychange'));
}

function grantPermOnly(config) {
  require('libs').hasPermission.mockImplementation(code => code === config.perm);
}

const BADGE_DATA = {data: {count: 5, expiring_count: 3, expired_count: 2}};

describe.each([
  ['无线电台执照 Badge Store', STORE_CONFIGS[0]],
  ['台站频率批复 Badge Store', STORE_CONFIGS[1]],
  ['合同协议 Badge Store', STORE_CONFIGS[2]],
])('%s', (name, config) => {
  let store;

  beforeEach(() => {
    mockHttpGet.mockReset();
    setToday('2026-09-18');
    store = freshStore(config.module);
    store._localToday = () => today;
  });

  afterEach(() => {
    if (store) store.stop();
    jest.restoreAllMocks();
  });

  it('有对应 view 权限时首次 start() 立即请求一次并更新计数', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(mockHttpGet).toHaveBeenCalledWith(config.url);
    await flush();
    expect(store.count).toBe(5);
    expect(store.expiringCount).toBe(3);
    expect(store.expiredCount).toBe(2);
    expect(store.loaded).toBe(true);
  });

  it('成功兼容裸返回结构（无 data 包装）', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue({count: 3, expiring_count: 1, expired_count: 2});
    store.start();
    await flush();
    expect(store.count).toBe(3);
    expect(store.expiringCount).toBe(1);
    expect(store.expiredCount).toBe(2);
    expect(store.loaded).toBe(true);
  });

  it('无权限时 start() 不请求且不注册监听器', () => {
    require('libs').hasPermission.mockReturnValue(false);
    const winAdd = jest.spyOn(window, 'addEventListener');
    const docAdd = jest.spyOn(document, 'addEventListener');
    store.start();
    expect(mockHttpGet).not.toHaveBeenCalled();
    expect(winAdd).not.toHaveBeenCalled();
    expect(docAdd).not.toHaveBeenCalled();
  });

  it('不存在固定轮询：推进计时器不产生新请求', () => {
    grantPermOnly(config);
    jest.useFakeTimers();
    mockHttpGet.mockReturnValue(new Promise(() => {}));
    store.start();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(24 * 60 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    store.stop();
    jest.advanceTimersByTime(24 * 60 * 60 * 1000);
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });

  it('同一自然日触发 focus 不重复请求', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    fireFocus();
    await flush();
    fireFocus();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });

  it('同一自然日恢复 visible 不重复请求', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    await flush();
    fireVisibility('visible');
    await flush();
    fireVisibility('visible');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });

  it('跨自然日后 focus 触发一次请求', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    setToday('2026-09-19');
    fireFocus();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
    // 同一自然日继续切换窗口不重复请求
    fireFocus();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
  });

  it('跨自然日后 visibilitychange 到 visible 触发一次请求', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    await flush();
    setToday('2026-09-20');
    fireVisibility('visible');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
    fireVisibility('visible');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
  });

  it('visibilityState 非 visible 时不请求', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    setToday('2026-09-21');
    fireVisibility('hidden');
    await flush();
    fireVisibility('hidden');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });

  it('focus 与 visibilitychange 连续触发不产生并发双请求', async () => {
    grantPermOnly(config);
    let resolveReq;
    mockHttpGet.mockImplementation(
      () => new Promise(resolve => {
        resolveReq = resolve;
      }));
    store.start();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    // 完成首次拉取（记录 2026-09-18 为最后成功日期）
    resolveReq(BADGE_DATA);
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    // 跨自然日：focus 与 visibilitychange 连续触发只允许产生一个补发请求
    let resolveReq2;
    mockHttpGet.mockImplementation(
      () => new Promise(resolve => {
        resolveReq2 = resolve;
      }));
    setToday('2026-09-19');
    fireFocus();
    fireVisibility('visible');
    fireFocus();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
    // 补发请求完成后同日再触发不再请求
    resolveReq2(BADGE_DATA);
    await flush();
    fireFocus();
    fireVisibility('visible');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
  });

  it('请求失败不更新最后成功日期，后续事件可以重试', async () => {
    grantPermOnly(config);
    mockHttpGet.mockRejectedValueOnce(new Error('网络错误'));
    store.start();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(store.loaded).toBe(false);
    // 失败后同日 focus 允许重试
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    fireFocus();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
    expect(store.loaded).toBe(true);
    // 成功后同日不再重复请求
    fireVisibility('visible');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2);
  });

  it('请求失败保留原有 Badge 数值且 loaded 不回退', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    await flush();
    expect(store.count).toBe(5);
    mockHttpGet.mockRejectedValue(new Error('网络错误'));
    setToday('2026-09-22');
    fireFocus();
    await flush();
    expect(store.count).toBe(5);
    expect(store.expiringCount).toBe(3);
    expect(store.expiredCount).toBe(2);
    expect(store.loaded).toBe(true);
  });

  it('重复 start() 不重复注册监听器或初始化请求', async () => {
    grantPermOnly(config);
    const winAdd = jest.spyOn(window, 'addEventListener');
    const docAdd = jest.spyOn(document, 'addEventListener');
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    store.start();
    store.start();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(winAdd.mock.calls.filter(([type]) => type === 'focus')).toHaveLength(1);
    expect(docAdd.mock.calls.filter(([type]) => type === 'visibilitychange')).toHaveLength(1);
  });

  it('stop() 后事件不再触发请求，重复 stop() 安全', async () => {
    grantPermOnly(config);
    const winRemove = jest.spyOn(window, 'removeEventListener');
    const docRemove = jest.spyOn(document, 'removeEventListener');
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    store.start();
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    store.stop();
    store.stop();
    expect(winRemove).toHaveBeenCalledWith('focus', expect.any(Function));
    expect(docRemove).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
    setToday('2026-09-23');
    fireFocus();
    fireVisibility('visible');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });

  it('fetch() 返回 Promise；无权限时返回已解决 Promise 且不请求', async () => {
    grantPermOnly(config);
    mockHttpGet.mockResolvedValue(BADGE_DATA);
    const promise = store.fetch();
    expect(promise && typeof promise.then === 'function').toBe(true);
    await promise;
    expect(mockHttpGet).toHaveBeenCalledWith(config.url);

    require('libs').hasPermission.mockReturnValue(false);
    await store.fetch();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);
  });
});

describe('三个 Badge Store 的请求面', () => {
  it('只请求各自 badge 统计接口，从不请求批复 popup 或 ack 接口', async () => {
    for (const config of STORE_CONFIGS) {
      const store = freshStore(config.module);
      store._localToday = () => today;
      grantPermOnly(config);
      mockHttpGet.mockResolvedValue(BADGE_DATA);
      store.start();
      await flush();
      // 模拟完整生命周期：跨日 focus + visible + 跨日再刷新
      setToday('2026-09-19');
      fireFocus();
      fireVisibility('visible');
      await flush();
      setToday('2026-09-20');
      fireVisibility('visible');
      await flush();
      store.stop();
    }
    const urls = mockHttpGet.mock.calls.map(([url]) => String(url));
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(url).toMatch(/\/badge\/$/);
      expect(url).not.toContain('popup');
      expect(url).not.toContain('ack');
    }
    // 三个 store 各自的 badge URL 均被请求过
    expect(urls.filter(u => u === '/api/radio-license/badge/').length).toBeGreaterThan(0);
    expect(urls.filter(u => u === '/api/radio-license/approvals/badge/').length).toBeGreaterThan(0);
    expect(urls.filter(u => u === '/api/contract-agreement/badge/').length).toBeGreaterThan(0);
  });
});
