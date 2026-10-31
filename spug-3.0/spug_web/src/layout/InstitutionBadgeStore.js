/**
 * 全局"制度管理"菜单红点 Store（2026-10-31 二轮权限模型改造新增）
 *
 * - 数据来源 GET /api/institution/manuals/badge/（口径=当前用户为所有者
 *   或持 can_publish 授权手册中已提交编制待核对的文件数；expiring_count/
 *   expired_count 恒 0，仅为与公共基类契约对齐保留）
 * - 权限门 institution.manual.publish（后端 badge 接口 @auth 同口径）
 * - 刷新生命周期由 ExpiryBadgeStore 统一提供（事件驱动，无固定轮询）：
 *   登录立即获取；提交编制/发布真实成功后由页面调用 fetch()；跨自然日
 *   恢复焦点/可见时获取；同一自然日反复切换窗口不重复请求
 * - 拉取失败容错（静默忽略），不影响菜单正常渲染
 */
import { ExpiryBadgeStore } from './expiryBadgeStoreBase';

class InstitutionBadgeStore extends ExpiryBadgeStore {
  constructor() {
    super('institution.manual.publish', '/api/institution/manuals/badge/');
  }
}

export default new InstitutionBadgeStore();
