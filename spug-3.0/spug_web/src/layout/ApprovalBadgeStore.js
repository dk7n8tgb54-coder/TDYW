/**
 * 全局"台站频率批复"菜单红点 Store（2026-09 第二轮恢复）
 *
 * - 数据来源 GET /api/radio-license/approvals/badge/（后端全局只读统计，
 *   不按租户/账户/责任人过滤，不创建任何数据库副作用）
 * - 红点是全局状态数字：所有拥有 radio_license.approval.view 权限的
 *   账户看到相同值；不支持"已处理"、不支持手动清除
 * - 刷新生命周期由 ExpiryBadgeStore 统一提供（事件驱动，无固定轮询）：
 *   登录立即获取；增删改成功后由页面调用 fetch()；跨自然日恢复焦点/
 *   可见时获取；同一自然日反复切换窗口不重复请求
 * - 拉取失败容错（静默忽略），不影响菜单正常渲染
 */
import { ExpiryBadgeStore } from './expiryBadgeStoreBase';

class ApprovalBadgeStore extends ExpiryBadgeStore {
  constructor() {
    super('radio_license.approval.view', '/api/radio-license/approvals/badge/');
  }
}

export default new ApprovalBadgeStore();
