/**
 * 全局告警 Store
 *
 * - 30 秒轮询 /api/home/alert/?page=1&page_size=5 拉取未读数 + 最近告警
 * - 仅管理员（is_supper）启动轮询
 * - 铃铛组件读取 unreadCount 显示红点
 */
import { observable, runInAction } from 'mobx';
import { http } from 'libs';

const POLL_INTERVAL = 30 * 1000; // 30 秒

class AlertStore {
  @observable unreadCount = 0;
  @observable errorCount = 0;
  @observable recentAlerts = [];
  @observable loading = false;

  start = () => {
    if (sessionStorage.getItem('is_supper') !== 'true') return;
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
    http.get('/api/home/alert/', { params: { page: 1, page_size: 5 } })
      .then(res => {
        const data = res && (res.data || res);
        runInAction(() => {
          this.recentAlerts = data?.items ?? [];
          const summary = data?.summary ?? {};
          this.unreadCount = summary.unread_count ?? 0;
          this.errorCount = summary.error_count ?? 0;
        });
      })
      .catch(() => {});
  };

  fetchRecent = () => {
    this.loading = true;
    return http.get('/api/home/alert/', { params: { page: 1, page_size: 20 } })
      .then(res => {
        const data = res && (res.data || res);
        runInAction(() => {
          this.recentAlerts = data?.items ?? [];
          const summary = data?.summary ?? {};
          this.unreadCount = summary.unread_count ?? 0;
          this.errorCount = summary.error_count ?? 0;
          this.loading = false;
        });
      })
      .catch(() => {
        runInAction(() => { this.loading = false; });
      });
  };

  markAllRead = () => {
    return http.post('/api/home/alert/mark-read/', { all: true })
      .then(() => {
        runInAction(() => {
          this.unreadCount = 0;
        });
      });
  };
}

export default new AlertStore();
