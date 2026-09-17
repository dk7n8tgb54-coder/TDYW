/**
 * 低频到期类菜单红点 Store 公共基类（事件驱动刷新，无固定轮询）。
 *
 * 适用对象：无线电台执照 / 台站频率批复 / 合同协议等低频到期数据的
 * 菜单红圈数字。统一刷新生命周期：
 *
 * - start()：先检查对应 view 权限；有权限时立即调用一次 fetch()，
 *   并注册 window focus 与 document visibilitychange 监听；
 *   重复调用 start() 不会重复请求初始化数据或重复注册监听器。
 * - fetch()：静默失败（失败不弹窗、不清空已有数字、不更新最后成功日期，
 *   以便下次事件重试）；在途请求去重，focus 与 visibilitychange 连续
 *   触发只产生一个请求；返回 Promise 供 CRUD 成功回调或测试调用。
 * - 跨自然日刷新：window focus 或 document visibilitychange 到 visible 时，
 *   仅当客户端本地自然日（YYYY-MM-DD）与最后成功获取日期不同才请求；
 *   同一自然日内反复切换窗口不重复请求。
 * - stop()：移除监听器并清理启动状态，重复调用安全无副作用。
 *
 * 约束：不使用 setInterval / 循环 setTimeout；不在此层维护各模块的
 * 统计口径（口径由后端 badge 接口决定）。
 */
import { observable, runInAction } from 'mobx';
import { http, hasPermission } from 'libs';

// 客户端本地自然日，格式 YYYY-MM-DD（跨自然日判断依据）
export function localToday() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export class ExpiryBadgeStore {
  @observable count = 0;         // 红点总数
  @observable expiringCount = 0; // 即将到期
  @observable expiredCount = 0;  // 已过期
  @observable loaded = false;    // 是否已成功拉取过（首次成功前不渲染红点，避免闪烁）

  /**
   * @param {string} perm   查看权限编码（如 radio_license.license.view）
   * @param {string} url    后端 badge 统计接口地址
   */
  constructor(perm, url) {
    this.perm = perm;
    this.url = url;
    this._started = false;
    this._inFlight = null;
    this._lastSuccessDate = null; // 最后成功获取的本地自然日
    // 绑定到实例，保证 add/removeEventListener 引用一致
    this._handleFocus = () => {
      this._refreshIfCrossDay();
    };
    this._handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        this._refreshIfCrossDay();
      }
    };
  }

  // 独立成实例方法，便于测试注入模拟自然日
  _localToday() {
    return localToday();
  }

  start = () => {
    if (this._started) return;
    // 无权限：不请求接口、不注册事件监听器、不显示红点
    if (!hasPermission(this.perm)) return;
    this._started = true;
    window.addEventListener('focus', this._handleFocus);
    document.addEventListener('visibilitychange', this._handleVisibility);
    // 登录进入主布局立即获取一次
    this.fetch();
  };

  stop = () => {
    if (!this._started) return;
    this._started = false;
    window.removeEventListener('focus', this._handleFocus);
    document.removeEventListener('visibilitychange', this._handleVisibility);
  };

  fetch = () => {
    if (!hasPermission(this.perm)) return Promise.resolve();
    // 在途请求去重：同一时刻只允许一个请求
    if (this._inFlight) return this._inFlight;
    const request = http.get(this.url)
      .then(res => {
        const data = res && (res.data || res);
        runInAction(() => {
          this.count = data?.count ?? 0;
          this.expiringCount = data?.expiring_count ?? 0;
          this.expiredCount = data?.expired_count ?? 0;
          this.loaded = true;
        });
        // 记录最后成功获取的本地自然日（失败路径不记录，下次事件可重试）
        this._lastSuccessDate = this._localToday();
      })
      .catch(() => {
        // 静默失败：保留旧数字与旧日期，不清空、不额外弹窗，不影响菜单渲染
      })
      .then(() => {
        if (this._inFlight === request) this._inFlight = null;
      });
    this._inFlight = request;
    return request;
  };

  // focus / visible 事件统一入口：仅跨自然日（或上次失败）时请求
  _refreshIfCrossDay = () => {
    if (this._inFlight) return;
    if (this._lastSuccessDate === this._localToday()) return;
    this.fetch();
  };
}
