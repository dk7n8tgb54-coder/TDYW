/**
 * 全局"无线电台执照"菜单红点 Store
 *
 * - 数据来源 GET /api/radio-license/badge/（当前用户负责且未 ack 的到期统计）
 * - 刷新生命周期由 ExpiryBadgeStore 统一提供（事件驱动，无固定轮询）：
 *   登录立即获取；增删改成功后由页面调用 fetch()；跨自然日恢复焦点/
 *   可见时获取；同一自然日反复切换窗口不重复请求
 * - 弹窗提醒"已处理"（ack）成功后仍会调用 fetch()（既有行为保留）
 * - 拉取失败容错（静默忽略），不影响菜单正常渲染
 */
import { ExpiryBadgeStore } from './expiryBadgeStoreBase';

class RadioLicenseBadgeStore extends ExpiryBadgeStore {
  constructor() {
    super('radio_license.license.view', '/api/radio-license/badge/');
  }
}

export default new RadioLicenseBadgeStore();
