/**
 * captureUploadTargetContext - 上传目标上下文捕获（纯函数）
 *
 * 从 navigationStore + sessionStorage 当场快照不可变上传目标上下文，
 * 后续无论用户切换目录/空间/离开党建页面，本批任务都使用此快照。
 *
 * 提取为独立纯函数模块的原因：
 *   1. 逻辑不依赖 Store 实例状态，只读 rootStore.navigationStore 和 sessionStorage
 *   2. 便于单元测试（避免 import 含装饰器的 UploadCoreStore 触发 jest babel 配置问题）
 *   3. 单一职责：上下文捕获逻辑独立于 Store 生命周期
 *
 * 返回对象经 Object.freeze 保护，所有上传相关请求（transfer create /
 * file upload / chunk upload / merge / merge_status / folder create）
 * 都从此快照读取 systemFolderCode/tenantId/isPublic/folderId，
 * 不再依赖可能变化的 systemFolderContext 全局变量或 navigationStore。
 */
import { PARTY_BUILDING_DOCUMENTS_CODE } from 'libs/systemFolderContext';

/**
 * @param {Object} rootStore - uploadCoreStore.rootStore（含 navigationStore）
 * @param {Object} [options]
 * @param {string|null} [options.systemFolderCode] - 显式系统目录 code（拖拽层党建模式会传 PARTY_BUILDING_DOCUMENTS_CODE）
 * @param {string} [options.targetPathLabel] - 用于 UI 提示的目标路径文本
 * @returns {Readonly<{folderId: number|null, isPublic: boolean, tenantId: string, systemFolderCode: string|null, targetPathLabel: string}>}
 */
export function captureUploadTargetContext(rootStore, options = {}) {
  const nav = rootStore?.navigationStore;
  const folderId = nav?.getUploadTargetFolderId?.() ?? null;
  const isPublic = nav?.isPublic ?? false;
  // tenantId 必须当场快照，不能在请求时重新读取 sessionStorage
  const tenantId = isPublic ? 'public' : (sessionStorage.getItem('tenant_id') || 'default');
  // 党建模式由调用方显式传入；普通模式恒为 null，避免残留
  const explicitCode = options.systemFolderCode === PARTY_BUILDING_DOCUMENTS_CODE
    ? PARTY_BUILDING_DOCUMENTS_CODE
    : null;
  // 双重保护：若调用方未传但当前 navigationStore 处于党建锁定模式，也使用党建 code
  const navCode = nav?.systemFolderCode === PARTY_BUILDING_DOCUMENTS_CODE
    ? PARTY_BUILDING_DOCUMENTS_CODE
    : null;
  const systemFolderCode = explicitCode || navCode || null;

  const ctx = {
    folderId,
    isPublic,
    tenantId,
    systemFolderCode,
    targetPathLabel: options.targetPathLabel || '',
  };
  return Object.freeze(ctx);
}

export default captureUploadTargetContext;
