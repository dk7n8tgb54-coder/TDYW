/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, action } from "mobx";
import { http } from 'libs';

class Store {
  @observable records = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};
  @observable addUpdateVisible = false;  // 添加动态弹窗的可见性
  @observable statistics = null;
  @observable systemNames = [];  // 系统名称列表
  @observable eventTypes = [];  // 事件类型列表（从API加载）
  @observable eventTypeModalVisible = false;  // 事件类型管理弹窗
  @observable pagination = {    // 分页信息
    page: 1,
    page_size: 50,
    total_count: 0,
    total_pages: 0
  };

  // 筛选条件
  @observable f_status;
  @observable f_severity;
  @observable f_date_range;
  @observable f_system_name;

  get dataSource() {
    // 后端分页，前端直接使用records
    return this.records;
  }

  @action fetchRecords = () => {
    this.isFetching = true;
    const filters = {};
    if (this.f_status) filters.status = this.f_status;
    if (this.f_severity) filters.severity = this.f_severity;
    if (this.f_system_name) filters.system_name = this.f_system_name;
    if (this.f_date_range && this.f_date_range.length === 2) {
      filters.date_range = [
        this.f_date_range[0].format('YYYY-MM-DD'),
        this.f_date_range[1].format('YYYY-MM-DD')
      ];
    }

    // 添加分页参数
    filters.page = this.pagination.page;
    filters.page_size = this.pagination.page_size;

    return http.get('/api/runlog/', {params: filters})
      .then(res => {
        this.records = res.logs || [];
        // 保存系统名称列表
        this.systemNames = res.system_names || [];
        // 保存分页信息
        if (res.pagination) {
          this.pagination = res.pagination;
        }
        return res;
      })
      .catch(e => {
        console.error('[运行日志] 获取记录失败:', e);
        throw e;
      })
      .finally(() => this.isFetching = false);
  };

  @action fetchStatistics = () => {
    http.get('/api/runlog/statistics/')
      .then(res => {
        this.statistics = res;
      })
      .catch(e => {
        console.error('[运行日志] 获取统计失败:', e);
      });
  };

  @action fetchEventTypes = () => {
    http.get('/api/runlog/event_types/')
      .then(res => {
        this.eventTypes = res || [];
      })
      .catch(e => {
        console.error('[运行日志] 获取事件类型失败:', e);
      });
  };

  @action showEventTypeModal = () => {
    this.eventTypeModalVisible = true;
    this.fetchEventTypes();  // 刷新列表
  };

  @action hideEventTypeModal = () => {
    this.eventTypeModalVisible = false;
  };

  @action addEventType = (data) => {
    return http.post('/api/runlog/event_types/', data)
      .then(res => {
        this.fetchEventTypes();  // 刷新列表
        return res;
      })
      .catch(e => {
        console.error('[运行日志] 添加事件类型失败:', e);
        throw e;
      });
  };

  @action updateEventType = (id, data) => {
    return http.put('/api/runlog/event_types/', { id, ...data })
      .then(res => {
        this.fetchEventTypes();  // 刷新列表
        return res;
      })
      .catch(e => {
        console.error('[运行日志] 更新事件类型失败:', e);
        throw e;
      });
  };

  @action deleteEventType = (id) => {
    return http.delete('/api/runlog/event_types/', { params: { id } })
      .then(res => {
        this.fetchEventTypes();  // 刷新列表
        return res;
      })
      .catch(e => {
        console.error('[运行日志] 删除事件类型失败:', e);
        throw e;
      });
  };

  @action showForm = (info = {}, isViewMode = false) => {
    this.formVisible = true;
    this.record = {...info, isViewMode};
  };

  @action showAddUpdateForm = (info = {}) => {
    this.formVisible = true;
    this.record = {...info, isAddUpdateMode: true};  // 标记为添加动态模式
  };

  @action setFilter = (key, value) => {
    this[`f_${key}`] = value;
    this.pagination.page = 1;  // 筛选时重置到第一页
    this.fetchRecords();
  };

  @action setPage = (page, pageSize) => {
    this.pagination.page = page;
    if (pageSize) {
      this.pagination.page_size = pageSize;
    }
    this.fetchRecords();
  };
}

export default new Store()
