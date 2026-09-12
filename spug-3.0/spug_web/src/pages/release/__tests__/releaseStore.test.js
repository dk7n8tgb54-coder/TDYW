/**
 * 更新日志 Store 行为测试
 *
 * 真实执行 store 代码路径（mobx store + mock http），验证：
 * - 未读数：以服务端 unread_count 为准写入 store，缺少时回退为条目数
 * - 弹窗开关：show_after_update 随未读接口写入 store，字段缺失视为开启
 * - HTTP 200 + error：不得视为成功（返回 null，未读状态保持不变）
 * - 请求失败（拦截器 reject）：返回 null 不抛出
 * - markRead / acknowledge：调用对应接口后重新拉取未读（以服务端状态为准）
 * - 标记已读失败：不得当作已读，不重新拉取
 */
const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: jest.fn(),
  },
  X_TOKEN: 'test-token',
}));

// 用 require 而非 import：import 会被提升到 mock 变量声明之前
const store = require('../store').default;

const UNREAD_API = '/api/system/release-notes/unread/';
const SETTINGS_API = '/api/system/release-notes/settings/';

describe('ReleaseNoteStore 行为', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.setUnread([], 0);
    store.checked = false;
    store.loading = false;
    store.drawerVisible = false;
    store.showAfterUpdate = true;
  });

  test('未读数：以服务端 unread_count 为准写入 store', async () => {
    mockHttpGet.mockResolvedValueOnce({
      unread_count: 7,
      has_required: false,
      current_version: 'v3.3.4',
      items: [{id: 1, version: 'v3.3.4', title: '更新A', is_required: false}],
    });

    const items = await store.fetchUnread();

    expect(mockHttpGet).toHaveBeenCalledWith(UNREAD_API);
    expect(items).toHaveLength(1);
    expect(store.unreadCount).toBe(7);
    expect(store.currentVersion).toBe('v3.3.4');
    expect(store.checked).toBe(true);
    expect(store.loading).toBe(false);
  });

  test('弹窗开关：show_after_update=false 写入 store，true 保持开启', async () => {
    mockHttpGet.mockResolvedValueOnce({unread_count: 0, show_after_update: false, items: []});
    await store.fetchUnread();
    expect(store.showAfterUpdate).toBe(false);

    mockHttpGet.mockResolvedValueOnce({unread_count: 0, show_after_update: true, items: []});
    await store.fetchUnread();
    expect(store.showAfterUpdate).toBe(true);
  });

  test('弹窗开关兼容：响应缺少 show_after_update 时视为开启', async () => {
    store.showAfterUpdate = false;
    mockHttpGet.mockResolvedValueOnce({unread_count: 0, items: []});

    await store.fetchUnread();

    expect(store.showAfterUpdate).toBe(true);
  });

  test('fetchPopupSetting：以服务端偏好写入 store，失败返回 null 且状态不变', async () => {
    mockHttpGet.mockResolvedValueOnce({show_after_update: false});
    expect(await store.fetchPopupSetting()).toBe(false);
    expect(store.showAfterUpdate).toBe(false);
    expect(mockHttpGet).toHaveBeenCalledWith(SETTINGS_API);

    mockHttpGet.mockResolvedValueOnce({});       // 缺字段视为开启
    expect(await store.fetchPopupSetting()).toBe(true);
    expect(store.showAfterUpdate).toBe(true);

    store.showAfterUpdate = false;
    mockHttpGet.mockRejectedValueOnce(new Error('network down'));
    expect(await store.fetchPopupSetting()).toBeNull();
    expect(store.showAfterUpdate).toBe(false);
  });

  test('savePopupSetting：调用设置接口成功后才更新本地偏好', async () => {
    mockHttpPut.mockResolvedValueOnce({show_after_update: false});

    expect(await store.savePopupSetting(false)).toBe(false);

    expect(mockHttpPut).toHaveBeenCalledWith(SETTINGS_API, {show_after_update: false});
    expect(store.showAfterUpdate).toBe(false);
  });

  test('savePopupSetting 失败：不得当作保存成功，偏好保持原值', async () => {
    store.showAfterUpdate = true;
    mockHttpPut.mockRejectedValueOnce(new Error('HTTP 200 + error'));

    await expect(store.savePopupSetting(false)).rejects.toBeDefined();

    expect(mockHttpPut).toHaveBeenCalledWith(SETTINGS_API, {show_after_update: false});
    expect(store.showAfterUpdate).toBe(true);
  });

  test('未读数回退：响应缺少 unread_count 时取条目数', async () => {
    mockHttpGet.mockResolvedValueOnce({
      items: [{id: 1}, {id: 2}],
    });

    await store.fetchUnread();

    expect(store.unreadCount).toBe(2);
  });

  test('HTTP 200 + error：不得视为成功，未读状态保持不变', async () => {
    store.setUnread([{id: 9, title: '已存在未读'}], 1);
    mockHttpGet.mockResolvedValueOnce({error: '登录状态异常'});

    const result = await store.fetchUnread();

    expect(result).toBeNull();
    // 不得把失败响应当成“没有未读”而清空状态
    expect(store.unreadCount).toBe(1);
    expect(store.unreadItems).toHaveLength(1);
    expect(store.checked).toBe(true);
    expect(store.loading).toBe(false);
  });

  test('请求失败（拦截器 reject）：返回 null 不抛出', async () => {
    mockHttpGet.mockRejectedValueOnce(new Error('network down'));

    const result = await store.fetchUnread();

    expect(result).toBeNull();
    expect(store.checked).toBe(true);
    expect(store.loading).toBe(false);
    expect(store.unreadCount).toBe(0);
  });

  test('markRead：调用已读接口成功后重新拉取未读', async () => {
    mockHttpPost.mockResolvedValueOnce({});
    mockHttpGet.mockResolvedValueOnce({unread_count: 0, items: []});

    await store.markRead(3);

    expect(mockHttpPost).toHaveBeenCalledWith('/api/system/release-notes/3/read/', {});
    expect(store.unreadCount).toBe(0);
    expect(store.unreadItems).toHaveLength(0);
  });

  test('markRead 失败：不得当作已读，不重新拉取未读', async () => {
    store.setUnread([{id: 3}], 1);
    mockHttpPost.mockRejectedValueOnce(new Error('HTTP 200 + error'));

    await expect(store.markRead(3)).rejects.toBeDefined();

    expect(mockHttpPost).toHaveBeenCalledWith('/api/system/release-notes/3/read/', {});
    expect(mockHttpGet).not.toHaveBeenCalled();
    expect(store.unreadCount).toBe(1);
  });

  test('acknowledge：调用确认接口成功后重新拉取未读', async () => {
    mockHttpPost.mockResolvedValueOnce({});
    mockHttpGet.mockResolvedValueOnce({unread_count: 0, items: []});

    await store.acknowledge(4);

    expect(mockHttpPost).toHaveBeenCalledWith('/api/system/release-notes/4/ack/', {});
    expect(store.unreadCount).toBe(0);
  });
});
