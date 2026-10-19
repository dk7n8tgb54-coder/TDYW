/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生维护台账模板 Store（2026-10-18 正式接入）。
 *
 * 状态：模板列表、当前模板详情（含草稿内容与版本列表）、编辑视图开关。
 * 与 Excel 模板管理同权限码（ledger_template.*），服务端独立校验；
 * 草稿保存 = 整体替换（快照+绑定+纸张一起 PUT）；发布 = 服务端把草稿
 * 快照落为不可变版本（重复发布产生新版本号，历史台账不回溯）。
 * 编辑器数据经消息桥注入 iframe，保存/发布前由宿主 collect 全量状态。
 */
import {observable, action} from 'mobx';
import {message} from 'antd';
import {http} from 'libs';

export const API = '/api/equipment-lifecycle/native-templates';

export class NativeTemplateStore {
  @observable list = [];
  @observable loading = false;
  @observable detail = null;      // 模板详情（含 draft/versions）
  @observable editing = false;    // 是否处于编辑视图（iframe 编辑器）
  @observable creating = false;   // 新建模态提交中
  @observable saving = false;     // 草稿保存中
  @observable publishing = false; // 发布中
  @observable editorDirty = false; // 编辑器推送的未保存标记
  @observable editorMeta = null;   // 编辑器推送的草稿元信息

  @action applyDetail(detail) {
    const payload = detail && detail.data ? detail.data : detail;
    this.detail = payload;
  }

  async fetchList() {
    action(() => { this.loading = true; })();
    try {
      const res = await http.get(`${API}/`);
      action(() => {
        this.list = (res && res.data) || [];
      })();
    } finally {
      action(() => { this.loading = false; })();
    }
  }

  async fetchDetail(id) {
    const res = await http.get(`${API}/${id}/`);
    this.applyDetail(res);
    return this.detail;
  }

  async createTemplate(form) {
    this.creating = true;
    try {
      const res = await http.post(`${API}/`, form);
      this.applyDetail(res);
      message.success('模板已创建，请在编辑器中绘制底表并保存草稿');
      return this.detail;
    } finally {
      action(() => { this.creating = false; })();
    }
  }

  async saveDraft(draft) {
    this.saving = true;
    try {
      const res = await http.put(`${API}/${this.detail.id}/draft/`, draft);
      this.applyDetail(res);
      message.success('草稿已保存');
      return this.detail;
    } finally {
      action(() => { this.saving = false; })();
    }
  }

  async publish() {
    this.publishing = true;
    try {
      const res = await http.post(`${API}/${this.detail.id}/publish/`);
      this.applyDetail(res);
      message.success(`已发布 v${this.detail.latest_version_no}，新台账将使用该版本`);
      return this.detail;
    } finally {
      action(() => { this.publishing = false; })();
    }
  }

  async deactivate(id) {
    await http.post(`${API}/${id}/deactivate/`);
    message.success('已停用');
  }

  async destroy(id) {
    await http.delete(`${API}/${id}/`);
    message.success('模板已删除');
  }

  @action setEditing(editing) {
    this.editing = editing;
    if (!editing) {
      this.editorDirty = false;
      this.editorMeta = null;
    }
  }

  @action applyEditorMeta(meta) {
    this.editorMeta = meta;
    this.editorDirty = !!meta.dirty;
  }
}

export default new NativeTemplateStore();
