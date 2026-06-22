/**
 * 全局"无线电台执照"菜单红点 Store
 *
 * - 5 分钟轮询 /api/radio-license/badge/ 拉取即将到期+已过期数量
 * - 仅在有 radio_license.license.view 权限时拉取
 * - 暴露 observe() / get() 供 Sider 等组件读取
 * - 拉取失败容错（静默忽略），不影响菜单正常渲染
 */
import { observable, runInAction } from 'mobx';
import { http, hasPermission } from 'libs';

const POLL_INTERVAL = 5 * 60 * 1000; // 5 分钟

class RadioLicenseBadgeStore {
  @observable count = 0;        // 红点总数（即将到期 + 已过期）
  @observable expiringCount = 0; // 即将到期
  @observable expiredCount = 0;   // 已过期
  @observable loaded = false;     // 是否已成功拉取过（首次拉取前不渲染红点，避免闪烁）

  start = () => {
    if (!hasPermission('radio_license.license.view')) return;
    // 立即拉取一次
    this.fetch();
    // 5 分钟轮询
    this._timer = setInterval(this.fetch, POLL_INTERVAL);
  };

  stop = () => {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  };

  fetch = () => {
    if (!hasPermission('radio_license.license.view')) return;
    http.get('/api/radio-license/badge/')
      .then(res => {
        const data = res && (res.data || res);
        runInAction(() => {
          this.count = data?.count ?? 0;
          this.expiringCount = data?.expiring_count ?? 0;
          this.expiredCount = data?.expired_count ?? 0;
          this.loaded = true;
        });
      })
      .catch(() => {
        // 静默失败：保留旧值，不影响菜单渲染
      });
  };
}

export default new RadioLicenseBadgeStore();
