/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 「设备管理 → 系统配置」维护入口状态管理（MobX, legacy decorators）。
 * 职责：系统候选（含系统档案引用字段与建档标记）、初始建档、参数定义维护。
 * 当前配置/变更历史/记录变更共用 systemConfig/store.js（同一时刻只挂载一处）。
 * 成功提示等待后端真实成功（http.js 拦截器统一提示 error，业务代码不重复提示）。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from '../constants';
import sharedStore from '../systemConfig/store';

class SystemConfigMaintainStore {
  // ========== 系统候选（config/system-options/，view 权限即可） ==========
  @observable systemOptions = [];
  @observable isOptionsFetching = false;
  @observable systemId = undefined;
  // 选中的系统行（含 system_model/manufacturer/callsign/work_frequency 引用字段）
  @observable currentSystem = null;

  // ========== 初始建档 ==========
  @observable baseline = null;
  @observable canEstablish = false;
  @observable blockReason = '';
  @observable isBaselineFetching = false;
  @observable baselineFormVisible = false;
  @observable isBaselineSubmitting = false;

  // ========== 参数定义维护 ==========
  @observable params = [];
  // 参数定义服务端分页（2026-10-31 上线前审查）：page_size 与后端上限一致
  // （200/页），超过 200 条时翻页可访问全部参数，不再静默遗漏
  @observable paramPage = 1;
  @observable paramPageSize = 200;
  @observable paramTotal = 0;
  @observable isParamsFetching = false;
  @observable paramFormVisible = false;
  @observable paramRecord = null;  // null=新增；对象=编辑
  @observable isParamSubmitting = false;

  // 系统候选/建档状态会被快速切换系统、卸载/重挂载并发触发；只接受最后
  // 一次响应，迟到的旧系统/卸载后响应不得回写（2026-10-31 上线前审查）。
  optionsRequestSeq = 0;
  baselineRequestSeq = 0;

  @action reset = () => {
    // 递增序号使卸载后到达的迟响应作废，不再回写已清空的视图数据
    this.optionsRequestSeq += 1;
    this.baselineRequestSeq += 1;
    this.systemOptions = [];
    this.systemId = undefined;
    this.currentSystem = null;
    this.baseline = null;
    this.canEstablish = false;
    this.blockReason = '';
    this.params = [];
    this.paramPage = 1;
    this.paramTotal = 0;
    this.isOptionsFetching = false;
    this.isBaselineFetching = false;
    this.isParamsFetching = false;
    this.hideBaselineForm();
    this.hideParamForm();
    sharedStore.clearView();
  };

  fetchSystemOptions = () => {
    const seq = ++this.optionsRequestSeq;
    this.isOptionsFetching = true;
    return http.get(`${API_PREFIX}/config/system-options/`)
      .then(action(res => {
        if (seq !== this.optionsRequestSeq) return;
        this.systemOptions = res.items || [];
        // 候选晚于选择到达时补齐 currentSystem（?system= 直达场景）
        if (this.systemId) {
          this.currentSystem = this.systemOptions.find(s => s.id === this.systemId) || null;
        }
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (seq === this.optionsRequestSeq) this.isOptionsFetching = false;
      }));
  };

  @action selectSystem = (systemId) => {
    this.systemId = systemId;
    this.currentSystem = this.systemOptions.find(s => s.id === systemId) || null;
    // 切换系统即失效在途建档响应，并先清建档视图状态再拉取，避免旧系统
    // 的建档信息残留展示
    this.baselineRequestSeq += 1;
    this.baseline = null;
    this.canEstablish = false;
    this.blockReason = '';
    if (systemId) {
      this.fetchBaseline(systemId);
      sharedStore.refreshAll(systemId);
    }
  };

  fetchBaseline = (systemId) => {
    const seq = ++this.baselineRequestSeq;
    this.isBaselineFetching = true;
    return http.get(`${API_PREFIX}/systems/${systemId}/config/baseline/`)
      .then(action(res => {
        if (seq !== this.baselineRequestSeq) return;
        this.baseline = res.baseline || null;
        this.canEstablish = !!res.can_establish;
        this.blockReason = res.block_reason || '';
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        if (seq === this.baselineRequestSeq) this.isBaselineFetching = false;
      }));
  };

  @action showBaselineForm = () => {
    this.baselineFormVisible = true;
  };

  @action hideBaselineForm = () => {
    this.baselineFormVisible = false;
  };

  /** 建档提交：真实成功后刷新建档状态与当前配置（不乐观更新）。 */
  submitBaseline = (payload) => {
    this.isBaselineSubmitting = true;
    return http.post(`${API_PREFIX}/systems/${this.systemId}/config/baseline/`, payload)
      .then(action(res => {
        this.hideBaselineForm();
        this.fetchBaseline(this.systemId);
        sharedStore.fetchConfig(this.systemId);
        return res;
      }))
      .finally(action(() => {
        this.isBaselineSubmitting = false;
      }));
  };

  fetchParams = () => {
    this.isParamsFetching = true;
    return http.get(`${API_PREFIX}/config-params/`, {
      params: {page: this.paramPage, page_size: this.paramPageSize}})
      .then(action(res => {
        this.params = res.items || [];
        this.paramTotal = res.total || 0;
      }))
      .catch(action(() => {}))
      .finally(action(() => {
        this.isParamsFetching = false;
      }));
  };

  /** 参数定义翻页（服务端分页）：换页即拉取对应页数据。 */
  fetchParamsPage = (page) => {
    this.paramPage = page;
    return this.fetchParams();
  };

  @action showParamForm = (record) => {
    this.paramRecord = record || null;
    this.paramFormVisible = true;
  };

  @action hideParamForm = () => {
    this.paramFormVisible = false;
    this.paramRecord = null;
  };

  /** 参数定义提交（id 空=新增）：成功后刷新参数清单（新增回到第 1 页，
   * 编辑留在当前页），选中系统时同步当前配置。 */
  submitParam = (payload, id) => {
    this.isParamSubmitting = true;
    const request = id
      ? http.put(`${API_PREFIX}/config-params/${id}/`, payload)
      : http.post(`${API_PREFIX}/config-params/`, payload);
    return request
      .then(action(res => {
        this.hideParamForm();
        if (!id) this.paramPage = 1;
        this.fetchParams();
        if (this.systemId) sharedStore.fetchConfig(this.systemId);
        return res;
      }))
      .finally(action(() => {
        this.isParamSubmitting = false;
      }));
  };
}

export default new SystemConfigMaintainStore();
