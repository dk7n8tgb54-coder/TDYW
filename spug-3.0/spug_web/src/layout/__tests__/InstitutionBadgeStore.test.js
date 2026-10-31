/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 制度管理菜单红点 Store 测试（2026-10-31 二轮权限模型改造新增）。
 *
 * 真实实例化 Store 单例，mock libs，钉死：
 * - 构造参数：perm=institution.manual.publish（红点门=发布授权口径）、
 *   badge 接口=/api/institution/manuals/badge/
 * - fetch 契约：解析 count/expiring_count/expired_count（后两者恒 0 也
 *   正确落位）、成功置 loaded
 * - 权限门：无 publish 权限时不发请求
 *
 * start/focus/跨自然日等完整生命周期由公共基类行为测试
 * expiryBadgeStoreBase.test.js 钉死，这里不重复。
 * 注意：不用顶层 import（会在 mockHttpGet 初始化前触发 libs 工厂），统一
 * 在常量声明后 require（expiryBadgeStoreBase.test.js 同款做法）。
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

const institutionBadge = require('../InstitutionBadgeStore').default;
const {hasPermission} = require('libs');

describe('InstitutionBadgeStore（制度管理菜单红点）', () => {
  beforeEach(() => {
    mockHttpGet.mockReset();
    hasPermission.mockImplementation(
      code => code === 'institution.manual.publish');
  });

  it('构造参数钉死：perm=institution.manual.publish，badge=/api/institution/manuals/badge/', () => {
    expect(institutionBadge.perm).toBe('institution.manual.publish');
    expect(institutionBadge.url).toBe('/api/institution/manuals/badge/');
  });

  it('fetch 拉取 badge 统计并解析 count/expiring_count/expired_count', async () => {
    mockHttpGet.mockResolvedValue(
      {data: {count: 4, expiring_count: 0, expired_count: 0}});
    await institutionBadge.fetch();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/institution/manuals/badge/');
    expect(institutionBadge.count).toBe(4);
    expect(institutionBadge.expiringCount).toBe(0);
    expect(institutionBadge.expiredCount).toBe(0);
    expect(institutionBadge.loaded).toBe(true);
  });

  it('成功兼容裸返回结构（无 data 包装）', async () => {
    mockHttpGet.mockResolvedValue({count: 2, expiring_count: 0, expired_count: 0});
    await institutionBadge.fetch();
    expect(institutionBadge.count).toBe(2);
    expect(institutionBadge.loaded).toBe(true);
  });

  it('无 publish 权限时 fetch 不发请求（红点门=发布授权口径）', async () => {
    hasPermission.mockReturnValue(false);
    await institutionBadge.fetch();
    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  it('请求失败静默容错：保留旧数字，loaded 不回退', async () => {
    mockHttpGet.mockResolvedValue({count: 6, expiring_count: 0, expired_count: 0});
    await institutionBadge.fetch();
    expect(institutionBadge.count).toBe(6);
    mockHttpGet.mockRejectedValue(new Error('网络错误'));
    await institutionBadge.fetch();
    expect(institutionBadge.count).toBe(6);
    expect(institutionBadge.loaded).toBe(true);
  });
});
