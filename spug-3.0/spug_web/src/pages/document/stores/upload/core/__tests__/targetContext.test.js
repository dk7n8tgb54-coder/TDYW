/**
 * 上传目标上下文固化测试（prompt 12.3 关键点）
 *
 * 验证 uploadCoreStore.captureUploadTargetContext 在以下场景的正确性：
 *   1. 普通模式 systemFolderCode=null（不携带党建上下文）
 *   2. 党建模式（navigationStore.systemFolderCode）正确捕获
 *   3. 显式传入 systemFolderCode 覆盖导航状态
 *   4. 返回对象被 Object.freeze 保护
 *   5. 公共空间 tenantId='public'，私有空间从 sessionStorage 读取
 *   6. folderId 从 navigationStore.getUploadTargetFolderId 读取
 *
 * 这些是"党建任务离开页面后仍携带正确 system_folder"的核心机制：
 * captureUploadTargetContext 在 drop 时把 systemFolderCode 固化为快照，
 * 后续 transfer/chunk/merge 请求从队列项读取，不再依赖全局 systemFolderContext。
 */
import { captureUploadTargetContext } from '../captureUploadTargetContext';
import { PARTY_BUILDING_DOCUMENTS_CODE } from 'libs/systemFolderContext';

// captureUploadTargetContext 是纯函数，只依赖 rootStore.navigationStore 和 sessionStorage，
// 无需实例化含装饰器的 UploadCoreStore，直接调用纯函数测试

describe('captureUploadTargetContext - 上传目标上下文固化', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  function makeRootStore(navOverrides = {}) {
    return {
      navigationStore: {
        getUploadTargetFolderId: () => null,
        isPublic: false,
        systemFolderCode: null,
        ...navOverrides,
      },
    };
  }

  it('普通模式：systemFolderCode=null，不携带党建上下文', () => {
    const rootStore = makeRootStore({
      getUploadTargetFolderId: () => 42,
      isPublic: false,
      systemFolderCode: null,
    });
    const ctx = captureUploadTargetContext(rootStore);
    expect(ctx.systemFolderCode).toBe(null);
    expect(ctx.folderId).toBe(42);
    expect(ctx.isPublic).toBe(false);
  });

  it('党建模式：navigationStore.systemFolderCode 正确捕获', () => {
    const rootStore = makeRootStore({
      getUploadTargetFolderId: () => 100,
      isPublic: true,
      systemFolderCode: PARTY_BUILDING_DOCUMENTS_CODE,
    });
    const ctx = captureUploadTargetContext(rootStore);
    expect(ctx.systemFolderCode).toBe(PARTY_BUILDING_DOCUMENTS_CODE);
    expect(ctx.folderId).toBe(100);
    expect(ctx.isPublic).toBe(true);
  });

  it('显式传入 systemFolderCode 覆盖导航状态（拖拽层党建模式）', () => {
    // 即使 navigationStore.systemFolderCode 为 null（用户可能刚切换），
    // 拖拽层显式传 systemFolderCode=PARTY_BUILDING_DOCUMENTS_CODE 也能正确捕获
    const rootStore = makeRootStore({ systemFolderCode: null });
    const ctx = captureUploadTargetContext(rootStore, {
      systemFolderCode: PARTY_BUILDING_DOCUMENTS_CODE,
    });
    expect(ctx.systemFolderCode).toBe(PARTY_BUILDING_DOCUMENTS_CODE);
  });

  it('非党建 code 传入被忽略（只接受 PARTY_BUILDING_DOCUMENTS_CODE）', () => {
    const rootStore = makeRootStore({ systemFolderCode: null });
    const ctx = captureUploadTargetContext(rootStore, {
      systemFolderCode: 'some_other_code',
    });
    expect(ctx.systemFolderCode).toBe(null);
  });

  it('返回对象被 Object.freeze 保护（修改抛错）', () => {
    const rootStore = makeRootStore();
    const ctx = captureUploadTargetContext(rootStore);
    expect(Object.isFrozen(ctx)).toBe(true);
    expect(() => { ctx.folderId = 999; }).toThrow();
    expect(() => { ctx.systemFolderCode = 'tampered'; }).toThrow();
  });

  it('公共空间 tenantId="public"', () => {
    const rootStore = makeRootStore({ isPublic: true });
    const ctx = captureUploadTargetContext(rootStore);
    expect(ctx.tenantId).toBe('public');
  });

  it('私有空间 tenantId 从 sessionStorage 读取', () => {
    sessionStorage.setItem('tenant_id', 'tenant_123');
    const rootStore = makeRootStore({ isPublic: false });
    const ctx = captureUploadTargetContext(rootStore);
    expect(ctx.tenantId).toBe('tenant_123');
  });

  it('私有空间 sessionStorage 无 tenant_id 时回退 "default"', () => {
    // beforeEach 已 clear，sessionStorage 无 tenant_id
    const rootStore = makeRootStore({ isPublic: false });
    const ctx = captureUploadTargetContext(rootStore);
    expect(ctx.tenantId).toBe('default');
  });

  it('targetPathLabel 透传（用于 UI 提示）', () => {
    const rootStore = makeRootStore();
    const ctx = captureUploadTargetContext(rootStore, {
      targetPathLabel: '党建文档 / 子目录',
    });
    expect(ctx.targetPathLabel).toBe('党建文档 / 子目录');
  });

  it('folderId 从 getUploadTargetFolderId 读取（null 表示根目录）', () => {
    const rootStore = makeRootStore({
      getUploadTargetFolderId: () => null,
    });
    const ctx = captureUploadTargetContext(rootStore);
    expect(ctx.folderId).toBe(null);
  });

  it('navigationStore 缺失时安全降级（不抛错）', () => {
    const rootStore = {};
    const ctx = captureUploadTargetContext(rootStore);
    expect(ctx.folderId).toBe(null);
    expect(ctx.isPublic).toBe(false);
    expect(ctx.systemFolderCode).toBe(null);
  });

  it('rootStore 缺失时安全降级（不抛错）', () => {
    const ctx = captureUploadTargetContext(null);
    expect(ctx.folderId).toBe(null);
    expect(ctx.isPublic).toBe(false);
    expect(ctx.systemFolderCode).toBe(null);
    expect(ctx.tenantId).toBe('default');
  });
});
