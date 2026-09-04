/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

// 关系角色选项（语义对齐后端 SystemDeviceRelation.ROLE_CHOICES）
export const ROLE_OPTIONS = [
  {value: 'primary', label: '主用'},
  {value: 'backup', label: '备用'},
  {value: 'member', label: '组成单元'},
];

// 关系状态选项
export const RELATION_STATUS_OPTIONS = [
  {value: 'active', label: '生效中'},
  {value: 'ended', label: '已退出'},
];

/**
 * 系统主数据 Store：列表/新建/编辑/删除 + 详情数据
 */
class SystemStore {
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable formVisible = false;
  @observable record = {};
  @observable current = null;   // 详情页当前系统
  @observable f_keyword = null;

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    if (this.f_keyword) params.keyword = this.f_keyword;
    return http.get('/api/equipment-lifecycle/systems/', {params})
      .then(res => {
        this.records = res.data;
        this.total = res.total;
      })
      .catch(() => {})
      .finally(() => {
        this.isFetching = false;
      })
  };

  fetchRecord = (id) => {
    return http.get('/api/equipment-lifecycle/systems/detail/', {params: {id}});
  };

  showForm = (record = {}) => {
    this.record = {...record};
    this.formVisible = true;
  };

  closeForm = () => {
    this.formVisible = false;
    this.record = {};
  };

  handleAdd = (values) => {
    return http.post('/api/equipment-lifecycle/systems/', values)
      .then(() => {
        this.closeForm();
        this.page = 1;
        this.fetchRecords();
      })
  };

  handleUpdate = (values) => {
    return http.put('/api/equipment-lifecycle/systems/', values)
      .then(() => {
        this.closeForm();
        this.fetchRecords();
      })
  };

  handleDelete = (id) => {
    return http.delete('/api/equipment-lifecycle/systems/', {params: {id}})
      .then(() => {
        // 删除最后一页最后一条后回退到前一页
        if (this.records.length === 1 && this.page > 1) this.page -= 1;
        this.fetchRecords();
      })
  };

  resetFilter = () => {
    this.f_keyword = null;
    this.page = 1;
    this.fetchRecords();
  };
}

/**
 * 系统—设备关系 Store：关系列表/新建/编辑/退出（历史只进不出，无删除）
 */
class RelationStore {
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 20;
  @observable systemOptions = [];
  @observable deviceOptions = [];
  @observable formVisible = false;
  @observable record = {};       // 编辑中的关系记录
  @observable f_status = null;      // 状态筛选
  @observable f_system_id = null;   // 系统筛选（关系维护页）
  @observable f_keyword = null;     // 设备编号/名称关键字（关系维护页）
  @observable deviceRelations = [];        // 设备视角的关系（设备详情弹窗）
  @observable deviceRelationsLoading = false;
  systemId = null;               // 固定系统范围（系统详情页）；null=全局
  deviceId = null;               // 固定设备上下文（设备详情弹窗）；null=非设备视角

  setSystem = (systemId) => {
    this.systemId = systemId;
    this.page = 1;
    this.f_status = null;
    this.f_keyword = null;
  };

  fetchRecords = () => {
    this.isFetching = true;
    const params = {page: this.page, page_size: this.pageSize};
    const systemFilter = this.systemId || this.f_system_id;
    if (systemFilter) params.system_id = systemFilter;
    if (this.f_status) params.status = this.f_status;
    if (this.f_keyword) params.keyword = this.f_keyword;
    return http.get('/api/equipment-lifecycle/system-relations/', {params})
      .then(res => {
        this.records = res.data;
        this.total = res.total;
      })
      .catch(() => {})
      .finally(() => {
        this.isFetching = false;
      })
  };

  // 设备视角：查询某设备的全部系统关系（设备详情弹窗，只读展示）
  fetchDeviceRelations = (deviceId) => {
    this.deviceRelationsLoading = true;
    return http.get('/api/equipment-lifecycle/system-relations/', {params: {device_id: deviceId, page_size: 50}})
      .then(res => {
        this.deviceRelations = res.data;
      })
      .catch(() => {})
      .finally(() => {
        this.deviceRelationsLoading = false;
      })
  };

  fetchSystemOptions = () => {
    return http.get('/api/equipment-lifecycle/system-relations/', {params: {system_options: 1}})
      .then(res => {
        this.systemOptions = res;
      })
      .catch(() => {})
  };

  // 设备下拉选项：keyword 为空时返回前 50 台，输入时过滤
  searchDevices = (keyword) => {
    return http.get('/api/equipment-lifecycle/system-relations/', {params: {device_options: 1, keyword: keyword || ''}})
      .then(res => {
        this.deviceOptions = res;
      })
      .catch(() => {})
  };

  showForm = (record = {}) => {
    this.record = {...record};
    this.deviceOptions = [];
    this.formVisible = true;
  };

  closeForm = () => {
    this.formVisible = false;
    this.record = {};
  };

  handleAdd = (values) => {
    return http.post('/api/equipment-lifecycle/system-relations/', values)
      .then(() => {
        this.closeForm();
        this.page = 1;
        this.fetchRecords();
        // 设备详情弹窗内新增关系时，同步刷新该设备视角的关系列表
        if (this.deviceId) this.fetchDeviceRelations(this.deviceId);
      })
  };

  handleUpdate = (values) => {
    return http.put('/api/equipment-lifecycle/system-relations/', values)
      .then(() => {
        this.closeForm();
        this.fetchRecords();
      })
  };

  handleExit = (id) => {
    return http.post('/api/equipment-lifecycle/system-relations/exit/', {id})
      .then(() => {
        if (this.records.length === 1 && this.page > 1) this.page -= 1;
        this.fetchRecords();
      })
  };

  resetFilter = () => {
    this.f_status = null;
    this.f_system_id = null;
    this.f_keyword = null;
    this.page = 1;
    this.fetchRecords();
  };
}

export const systemStore = new SystemStore();
export const relationStore = new RelationStore();
