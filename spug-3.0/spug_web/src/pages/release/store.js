/**
 * 系统版本更新日志 Store
 *
 * - 未读数量、未读列表由服务端 /api/system/release-notes/unread/ 提供，
 *   前端不使用 localStorage 作为已读依据。
 * - 普通更新调用 markRead，重要更新（is_required）调用 acknowledge，
 *   两者成功后都会重新拉取未读列表，保证以服务端状态为准。
 * - showAfterUpdate 为「每次更新后自动弹出更新日志」用户个人偏好（随未读接口下发，
 *   缺省视为开启，默认勾选）：关闭时通知组件不自动弹窗，用户从头像菜单
 *   「更新日志」查看，并可通过抽屉内的开关重新开启。
 */
import {observable, action, runInAction} from 'mobx';
import {http} from 'libs';

export const RELEASE_API = {
  version: '/api/system/version/',
  list: '/api/system/release-notes/',
  unread: '/api/system/release-notes/unread/',
  settings: '/api/system/release-notes/settings/',
  detail: id => `/api/system/release-notes/${id}/`,
  read: id => `/api/system/release-notes/${id}/read/`,
  ack: id => `/api/system/release-notes/${id}/ack/`,
  admin: '/api/system/release-notes/admin/',
  adminDetail: id => `/api/system/release-notes/admin/${id}/`,
  adminPublish: id => `/api/system/release-notes/admin/${id}/publish/`,
};

class ReleaseNoteStore {
  @observable currentVersion = '';
  @observable unreadCount = 0;
  @observable unreadItems = [];
  @observable loading = false;
  @observable checked = false;
  @observable showAfterUpdate = true;

  @observable drawerVisible = false;
  @observable versions = [];
  @observable detailItems = [];
  @observable selectedVersion = '';
  @observable listLoading = false;

  /**
   * 拉取未读更新。
   * 成功返回未读条目数组（可能为空数组）；请求失败或返回 HTTP 200 + error
   * 一律视为失败返回 null（调用方不得视为成功，不得据此清空未读状态）。
   */
  fetchUnread = () => {
    this.loading = true;
    return http.get(RELEASE_API.unread)
      .then(data => {
        const payload = data || {};
        if (payload.error) {
          runInAction(() => {
            this.loading = false;
            this.checked = true;
          });
          return null;
        }
        runInAction(() => {
          this.unreadItems = payload.items || [];
          this.unreadCount = payload.unread_count ?? (payload.items || []).length;
          this.currentVersion = payload.current_version || this.currentVersion;
          // 平台级弹窗开关：字段缺失（旧版本后端）时保持默认开启
          this.showAfterUpdate = payload.show_after_update !== false;
          this.loading = false;
          this.checked = true;
        });
        return this.unreadItems;
      })
      .catch(() => {
        runInAction(() => {
          this.loading = false;
          this.checked = true;
        });
        return null;
      });
  };

  fetchVersion = () => {
    return http.get(RELEASE_API.version)
      .then(data => {
        runInAction(() => {
          this.currentVersion = (data && data.version) || this.currentVersion;
        });
        return data;
      });
  };

  markRead = id => {
    return http.post(RELEASE_API.read(id), {}).then(() => this.fetchUnread());
  };

  acknowledge = id => {
    return http.post(RELEASE_API.ack(id), {}).then(() => this.fetchUnread());
  };

  /** 拉取当前用户的「每次更新后自动弹出更新日志」偏好（打开抽屉时刷新开关状态） */
  fetchPopupSetting = () => {
    return http.get(RELEASE_API.settings)
      .then(data => {
        runInAction(() => {
          this.showAfterUpdate = !data || data.show_after_update !== false;
        });
        return this.showAfterUpdate;
      })
      .catch(() => null);
  };

  /** 保存偏好；成功才更新本地状态，失败时保持原值并向上抛出（由拦截器提示） */
  savePopupSetting = next => {
    return http.put(RELEASE_API.settings, {show_after_update: !!next})
      .then(() => {
        runInAction(() => { this.showAfterUpdate = !!next; });
        return this.showAfterUpdate;
      });
  };

  openDrawer = () => {
    runInAction(() => { this.drawerVisible = true; });
    this.fetchPopupSetting();
    return this.fetchVersions();
  };

  closeDrawer = () => {
    runInAction(() => { this.drawerVisible = false; });
  };

  /** 拉取历史版本列表（按版本聚合） */
  fetchVersions = () => {
    return http.get(RELEASE_API.list, {params: {page: 1, page_size: 100}})
      .then(data => {
        const items = (data && data.items) || [];
        const versions = [];
        items.forEach(item => {
          const found = versions.find(v => v.version === item.version);
          if (found) {
            found.count += 1;
            if (item.publish_at > found.publish_at) found.publish_at = item.publish_at;
          } else {
            versions.push({version: item.version, count: 1, publish_at: item.publish_at});
          }
        });
        runInAction(() => {
          this.versions = versions;
          const first = versions[0];
          const current = versions.find(v => v.version === this.currentVersion);
          this.selectedVersion = (current || first) ? (current || first).version : '';
        });
        return this.selectedVersion ? this.fetchVersionDetail(this.selectedVersion) : [];
      })
      .catch(() => []);
  };

  selectVersion = version => {
    runInAction(() => { this.selectedVersion = version; });
    return this.fetchVersionDetail(version);
  };

  /** 拉取指定版本的更新条目（含正文） */
  fetchVersionDetail = version => {
    this.listLoading = true;
    return http.get(RELEASE_API.list, {
      params: {version, page: 1, page_size: 100, with_content: true}
    })
      .then(data => {
        runInAction(() => {
          this.detailItems = (data && data.items) || [];
          this.listLoading = false;
        });
        return this.detailItems;
      })
      .catch(() => {
        runInAction(() => {
          this.detailItems = [];
          this.listLoading = false;
        });
        return [];
      });
  };

  /** 供测试/外部直接写入未读状态 */
  @action
  setUnread(items, count) {
    this.unreadItems = items || [];
    this.unreadCount = count === undefined ? this.unreadItems.length : count;
  }
}

export default new ReleaseNoteStore();
