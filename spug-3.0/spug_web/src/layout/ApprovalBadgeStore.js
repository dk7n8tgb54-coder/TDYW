/**
 * 台站频率批复红点 Store。
 * 当前批复后端接口尚未挂载到 layout，因此这里只提供可复用配置，
 * 不会自行启动轮询；后端上线后由 layout 显式 start()。
 */
import { observable, runInAction } from 'mobx';
import { http, hasPermission } from 'libs';

const POLL_INTERVAL = 5 * 60 * 1000;

class ApprovalBadgeStore {
  @observable count = 0;
  @observable expiringCount = 0;
  @observable expiredCount = 0;
  @observable loaded = false;

  start = () => {
    if (!hasPermission('radio_license.approval.view')) return;
    this.fetch();
    this._timer = setInterval(this.fetch, POLL_INTERVAL);
  };

  stop = () => {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  };

  fetch = () => {
    if (!hasPermission('radio_license.approval.view')) return;
    http.get('/api/radio-license/approvals/badge/')
      .then(res => {
        const data = res && (res.data || res);
        runInAction(() => {
          this.count = data?.count ?? 0;
          this.expiringCount = data?.expiring_count ?? 0;
          this.expiredCount = data?.expired_count ?? 0;
          this.loaded = true;
        });
      })
      .catch(() => null);
  };
}

export default new ApprovalBadgeStore();
