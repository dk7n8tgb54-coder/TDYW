/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统履历事项分组状态管理（MobX, legacy decorators）。
 * 分组列表按系统分页；事项节点展开时按需加载（缓存 + 在途去重 + 失败重试）；
 * 健康状态变化走独立抽屉（按系统查询，事件类型固定 health）。
 * 履历只读：仅查询请求，无新增/修改/删除。
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { API_PREFIX } from './constants';

/** 事项唯一键：系统 + 聚合键（source_type + source_id）。 */
export function itemKey(systemId, sourceType, sourceId) {
  return `${systemId}:${sourceType}:${sourceId}`;
}

export class GroupStore {
  @observable groups = [];
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 10;
  @observable isFetching = false;
  @observable fetchFailed = false;

  // ========== 筛选条件 ==========
  @observable f_keyword = undefined;
  @observable f_event_type = undefined;
  @observable f_source_type = undefined;
  @observable f_range = undefined;

  // ========== 展开与按需加载 ==========
  @observable itemNodes = {}; // itemKey -> {status: loading|done|failed, nodes: []}

  // ========== 健康状态变化抽屉 ==========
  @observable healthDrawer = {
    visible: false, systemId: null, systemName: '',
    loading: false, failed: false, records: [],
  };

  // 请求版本号：分页/筛选快速切换时丢弃旧响应，防止旧数据覆盖新状态
  requestSeq = 0;
  // 事项节点在途请求：同一事项并发展开只发一次
  nodeRequests = {};

  @action resetFilter = () => {
    this.f_keyword = undefined;
    this.f_event_type = undefined;
    this.f_source_type = undefined;
    this.f_range = undefined;
    this.page = 1;
  };

  buildParams = () => {
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    if (this.f_event_type) params.event_type = this.f_event_type;
    if (this.f_source_type) params.source_type = this.f_source_type;
    if (this.f_range && this.f_range.length === 2) {
      params.occurred_from = this.f_range[0];
      params.occurred_to = this.f_range[1];
    }
    return params;
  };

  fetchGroups = () => {
    const seq = ++this.requestSeq;
    this.isFetching = true;
    return http.get(`${API_PREFIX}/system-event-groups/`, {params: this.buildParams()})
      .then(action(res => {
        if (seq !== this.requestSeq) return;
        this.groups = res.data || [];
        this.total = res.total || 0;
        this.fetchFailed = false;
      }))
      .catch(action(() => {
        if (seq !== this.requestSeq) return;
        this.fetchFailed = true;
      }))
      .finally(action(() => {
        if (seq === this.requestSeq) this.isFetching = false;
      }));
  };

  changePage = (page) => {
    this.page = page;
    this.fetchGroups();
  };

  loadItemNodes = (systemId, sourceType, sourceId) => {
    const key = itemKey(systemId, sourceType, sourceId);
    const cached = this.itemNodes[key];
    if (cached && cached.status === 'done') return Promise.resolve();
    if (this.nodeRequests[key]) return this.nodeRequests[key];
    this.itemNodes[key] = {status: 'loading', nodes: []};
    const request = http.get(`${API_PREFIX}/system-event-groups/nodes/`, {
      params: {system: systemId, source_type: sourceType, source_id: sourceId},
    })
      .then(action(res => {
        this.itemNodes[key] = {status: 'done', nodes: res.data || []};
      }))
      .catch(action(() => {
        this.itemNodes[key] = {status: 'failed', nodes: []};
      }))
      .finally(() => {
        delete this.nodeRequests[key];
      });
    this.nodeRequests[key] = request;
    return request;
  };

  /**
   * 事项展开/收起（antd 非受控展开，UI 由 Table 自管）：
   * 仅在展开时按需加载节点；重复展开命中缓存不再请求。
   */
  onItemExpand = (expanded, record, systemId) => {
    if (expanded && record.source_id) {
      this.loadItemNodes(systemId, record.source_type, record.source_id);
    }
  };

  openHealthDrawer = (group) => {
    const systemId = group.system.id;
    this.healthDrawer = {
      visible: true, systemId, systemName: group.system.name,
      loading: true, failed: false, records: [],
    };
    http.get(`${API_PREFIX}/systems/${systemId}/system-events/`, {
      params: {page: 1, page_size: 200, event_type: 'health'},
    })
      .then(action(res => {
        this.healthDrawer.loading = false;
        this.healthDrawer.records = res.data || [];
      }))
      .catch(action(() => {
        this.healthDrawer.loading = false;
        this.healthDrawer.failed = true;
      }));
  };

  closeHealthDrawer = () => {
    this.healthDrawer.visible = false;
  };
}

export default new GroupStore();
