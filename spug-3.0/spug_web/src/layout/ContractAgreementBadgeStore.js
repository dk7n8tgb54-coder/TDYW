/**
 * 全局"合同协议"菜单红点 Store
 *
 * - 数据来源 GET /api/contract-agreement/badge/（仅即将到期计入红点总数，
 *   已过期不计入提醒）
 * - 刷新生命周期由 ExpiryBadgeStore 统一提供（事件驱动，无固定轮询）：
 *   登录立即获取；增删改成功后由页面调用 fetch()；跨自然日恢复焦点/
 *   可见时获取；同一自然日反复切换窗口不重复请求
 * - 弹窗提醒"已处理"（ack）成功后仍会调用 fetch()（既有行为保留）
 * - 拉取失败容错（静默忽略），不影响菜单正常渲染
 */
import { ExpiryBadgeStore } from './expiryBadgeStoreBase';

class ContractAgreementBadgeStore extends ExpiryBadgeStore {
  constructor() {
    super('contract_agreement.agreement.view', '/api/contract-agreement/badge/');
  }
}

export default new ContractAgreementBadgeStore();
