/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统配置状态管理（MobX, legacy decorators）。
 * 服务两处入口（共用同一套当前配置/变更数据，同一时刻只挂载一处）：
 * - 「系统详情 → 配置」只读页签（2026-10-19 起：展示 + 详情 Drawer）；
 * - 「设备管理 → 系统配置」维护入口的配置/变更区域（写操作所在，
 *   建档/参数定义/系统候选在 systemConfigMaintain/store.js）。
 * 成功提示等待后端真实成功（http.js 拦截器统一提示 error，业务代码不重复提示）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from '../constants';

class SystemConfigStore {
  // ========== 当前配置 ==========
  @observable configItems = [];
  @observable configSystem = {};
  // 初始建档摘要（GET config 随响应返回；null=未建档）
  @observable configBaseline = null;
  @observable isConfigFetching = false;

  // ========== 配置变更历史 ==========
  @observable changes = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 10;
  @observable isChangesFetching = false;
  @observable f_status = undefined;
  @observable f_param = undefined;
  @observable f_created_range = undefined;

  // ========== 记录配置变更（Modal，非独立页面） ==========
  @observable formVisible = false;
  @observable isSubmitting = false;

  // ========== 变更详情（Drawer） ==========
  @observable detailVisible = false;
  @observable detail = {};
  @observable isDetailFetching = false;
  // 详情可能被多个入口并发刷新；只接受最后一次响应。
  detailRequestSeq = 0;

  // ========== 动作执行中（应用/验证/回退/取消/附件） ==========
  @observable isActionSubmitting = false;

  @action resetFilters = () => {
    this.f_status = undefined;
    this.f_param = undefined;
    this.f_created_range = undefined;
    this.page = 1;
  };

  // 清空视图数据：页签/维护页卸载时调用，避免其他系统展示被残留数据污染
  @action clearView = () => {
    this.configItems = [];
    this.configSystem = {};
    this.configBaseline = null;
    this.changes = [];
    this.total = 0;
    this.page = 1;
  };

  fetchConfig = (systemId) => {
    this.isConfigFetching = true;
    return http.get(`${API_PREFIX}/systems/${systemId}/config/`)
      .then(action(res => {
        this.configItems = res.items || [];
        this.configSystem = res.system || {};
        this.configBaseline = res.baseline || null;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isConfigFetching = false;
      }));
  };

  fetchChanges = (systemId) => {
    this.isChangesFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_status) params.status = this.f_status;
    if (this.f_param) params.param = this.f_param;
    if (this.f_created_range && this.f_created_range.length === 2) {
      params.created_from = this.f_created_range[0].format('YYYY-MM-DD HH:mm');
      params.created_to = this.f_created_range[1].format('YYYY-MM-DD HH:mm');
    }
    return http.get(`${API_PREFIX}/systems/${systemId}/config/changes/`, {params})
      .then(action(res => {
        this.changes = res.items || [];
        this.total = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isChangesFetching = false;
      }));
  };

  @action showForm = () => {
    this.formVisible = true;
  };

  @action hideForm = () => {
    this.formVisible = false;
  };

  /**
   * 提交配置变更：先创建变更（真实成功拿到编号），再上传收集到的附件文件。
   * 不做乐观更新；任一环节业务失败由拦截器提示（不重复提示）。
   */
  submitChange = (systemId, payload, files) => {
    this.isSubmitting = true;
    let created = null;
    return http.post(`${API_PREFIX}/config-changes/`, payload)
      .then(action(res => {
        created = res;
        const uploads = (files || []).map(file => {
          const formData = new FormData();
          formData.append('file', file);
          return http.post(
            `${API_PREFIX}/config-changes/${created.id}/attachments/`, formData);
        });
        // 附件上传失败的文件由拦截器提示，不阻断已创建的变更
        return Promise.all(uploads).catch(() => {});
      }))
      .then(action(() => {
        this.hideForm();
        this.refreshAll(systemId);
        return created;
      }))
      .finally(action(() => {
        this.isSubmitting = false;
      }));
  };

  refreshAll = (systemId) => {
    this.fetchConfig(systemId);
    this.fetchChanges(systemId);
  };

  showDetail = (id) => {
    this.detailVisible = true;
    this.detail = {};
    this.fetchDetail(id);
  };

  @action hideDetail = () => {
    this.detailVisible = false;
  };

  fetchDetail = (id) => {
    const seq = ++this.detailRequestSeq;
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX}/config-changes/${id}/`)
      .then(action(res => {
        if (seq === this.detailRequestSeq) this.detail = res;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (seq === this.detailRequestSeq) this.isDetailFetching = false;
      }));
  };

  applyChange = (id, systemId) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/config-changes/${id}/apply/`)
      .then(action(res => {
        this.detail = res;
        this.refreshAll(systemId);
        return res;
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  verifyChange = (id, systemId, verifyStatus, verifyNote) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/config-changes/${id}/verify/`, {
      verify_status: verifyStatus,
      verify_note: verifyNote || '',
    })
      .then(action(res => {
        this.detail = res;
        this.refreshAll(systemId);
        return res;
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  rollbackChange = (id, systemId) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/config-changes/${id}/rollback/`)
      .then(action(res => {
        this.refreshAll(systemId);
        return res;
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  cancelChange = (id, systemId) => {
    this.isActionSubmitting = true;
    return http.post(`${API_PREFIX}/config-changes/${id}/cancel/`)
      .then(action(res => {
        this.detail = res;
        this.refreshAll(systemId);
        return res;
      }))
      .finally(action(() => {
        this.isActionSubmitting = false;
      }));
  };

  fetchAttachments = (id) => {
    return http.get(`${API_PREFIX}/config-changes/${id}/attachments/`)
      .then(res => res.data || []);
  };

  uploadAttachment = (id, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return http.post(`${API_PREFIX}/config-changes/${id}/attachments/`, formData);
  };

  deleteAttachment = (id, attachmentId) => {
    return http.delete(`${API_PREFIX}/config-changes/${id}/attachments/${attachmentId}/`);
  };
}

export default new SystemConfigStore();
