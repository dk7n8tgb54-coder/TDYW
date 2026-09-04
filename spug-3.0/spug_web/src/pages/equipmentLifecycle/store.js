/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

/**
 * 设备生命周期状态管理 Store
 * 职责：设备档案（独立主数据）列表 + 详情 + 新建/编辑/删除。
 */
class Store {
  @observable records = [];          // 设备列表
  @observable isFetching = false;    // 列表加载状态
  @observable total = 0;             // 总数
  @observable page = 1;              // 当前页码
  @observable pageSize = 20;         // 每页数量

  @observable formVisible = false;   // 新建/编辑弹窗可见性
  @observable record = {};           // 当前编辑数据
  @observable detailVisible = false; // 详情弹窗可见性

  @observable locationChangeVisible = false;   // 变更位置弹窗可见性
  @observable locationHistoryVisible = false;  // 位置历史弹窗可见性
  @observable locationHistory = [];            // 位置历史列表
  @observable locationHistoryLoading = false;  // 位置历史加载状态

  // 筛选条件
  @observable f_device_sn = null;      // 设备编号/名称关键字
  @observable f_device_model = null;   // 设备型号
  @observable f_current_status = [];   // 当前设备状况（数组）

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.page,
      page_size: this.pageSize
    };
    if (this.f_device_sn) params.keyword = this.f_device_sn;
    if (this.f_device_model) params.device_model = this.f_device_model;
    if (this.f_current_status && this.f_current_status.length > 0) params.current_status = this.f_current_status;

    return http.get('/api/equipment-lifecycle/devices/', {params})
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
    return http.get('/api/equipment-lifecycle/devices/', {params: {id}});
  };

  // 详情打开后从后端拉取最新数据回填，不信任列表缓存数据；
  // 拉取失败时保留列表数据展示（错误已由 http 拦截器统一提示，不重复提示）
  showDetail = (record) => {
    this.detailVisible = true;
    this.record = {...record};
    this.fetchRecord(record.id)
      .then(res => {
        this.record = res;
      })
      .catch(() => {})
  };

  closeDetail = () => {
    this.detailVisible = false;
    this.record = {};
  };

  // ========== 设备档案 CRUD（equipment_lifecycle.device.manage） ==========
  showForm = (record = {}) => {
    this.record = {...record};
    this.formVisible = true;
  };

  closeForm = () => {
    this.formVisible = false;
    this.record = {};
  };

  handleAdd = (values) => {
    return http.post('/api/equipment-lifecycle/devices/', values)
      .then(() => {
        this.closeForm();
        this.page = 1;
        this.fetchRecords();
      })
  };

  handleUpdate = (values) => {
    return http.put('/api/equipment-lifecycle/devices/', values)
      .then(() => {
        this.closeForm();
        this.fetchRecords();
      })
  };

  handleDelete = (id) => {
    return http.delete('/api/equipment-lifecycle/devices/', {params: {id}})
      .then(() => {
        // 删除最后一页最后一条后回退到前一页
        if (this.records.length === 1 && this.page > 1) this.page -= 1;
        this.fetchRecords();
      })
  };

  // ========== 设备位置（equipment_lifecycle.device.manage / device.view） ==========
  showLocationChange = () => {
    this.locationChangeVisible = true;
  };

  closeLocationChange = () => {
    this.locationChangeVisible = false;
  };

  showLocationHistory = () => {
    this.locationHistoryVisible = true;
    this.fetchLocationHistory();
  };

  closeLocationHistory = () => {
    this.locationHistoryVisible = false;
    this.locationHistory = [];
  };

  fetchLocationHistory = () => {
    this.locationHistoryLoading = true;
    return http.get('/api/equipment-lifecycle/devices/location-history/', {
      params: {device_id: this.record.id}
    })
      .then(res => {
        this.locationHistory = res.data || [];
      })
      .catch(() => {})
      .finally(() => {
        this.locationHistoryLoading = false;
      })
  };

  // 位置变更走独立接口，不经过普通设备编辑；成功后重新拉取详情与列表，
  // 不做乐观更新（列表同步刷新以更新"当前位置"列）
  changeLocation = (values) => {
    const deviceId = this.record.id;
    return http.post('/api/equipment-lifecycle/devices/location-change/',
                     {...values, device_id: deviceId})
      .then(() => {
        this.closeLocationChange();
        return Promise.all([
          this.fetchRecord(deviceId).then(res => {
            this.record = res;
          }).catch(() => {}),
          this.fetchRecords(),
        ]);
      })
  };

  resetFilter = () => {
    this.f_device_sn = null;
    this.f_device_model = null;
    this.f_current_status = [];
    this.page = 1;
    this.fetchRecords();
  };
}

export default new Store()
