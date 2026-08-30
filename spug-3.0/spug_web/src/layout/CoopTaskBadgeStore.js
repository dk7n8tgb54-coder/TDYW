/**
 * 全局"协作任务"菜单红点 Store
 *
 * - 5 分钟轮询 /api/coop-task/badge/ 拉取交付待处理 + 待验收数量
 * - 仅在有 coop.task.view 权限时拉取（发起方与交付科室角色均含 view）
 * - 暴露 fetch() 供页面在关键动作后立即刷新
 * - 拉取失败容错（静默忽略），不影响菜单正常渲染
 */
import {observable, runInAction} from 'mobx';
import {http, hasPermission} from 'libs';

const POLL_INTERVAL = 5 * 60 * 1000; // 5 分钟

class CoopTaskBadgeStore {
  @observable count = 0;          // 红点总数（交付方待处理 + 发起方待验收）
  @observable inboxPending = 0;   // 本科室待交付/待重交
  @observable acceptPending = 0;  // 我发起的待验收
  @observable urgeUnread = 0;     // 未读催办
  @observable loaded = false;     // 是否已成功拉取过（首次拉取前不渲染红点，避免闪烁）

  start = () => {
    if (!hasPermission('coop.task.view')) return;
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
    if (!hasPermission('coop.task.view')) return;
    http.get('/api/coop-task/badge/')
      .then(res => {
        const data = res && (res.data || res);
        runInAction(() => {
          this.count = data?.count ?? 0;
          this.inboxPending = data?.inbox_pending ?? 0;
          this.acceptPending = data?.accept_pending ?? 0;
          this.urgeUnread = data?.urge_unread ?? 0;
          this.loaded = true;
        });
      })
      .catch(() => {
        // 静默失败：保留旧值，不影响菜单渲染
      });
  };
}

export default new CoopTaskBadgeStore();
