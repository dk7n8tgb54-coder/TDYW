/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 换班数据管理Store
 * 
 * 职责：
 * - 换班列表管理
 * - 换班CRUD操作
 * - 换班审批流程
 * - 批量换班
 */
import { observable, action } from 'mobx';
import { http } from 'libs';

class SwapStore {
  @observable swapList = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};

  /**
   * 获取换班列表
   * @param {Object} params - 查询参数
   * @param {string} params.start_date - 开始日期 (YYYY-MM-DD)
   * @param {string} params.end_date - 结束日期 (YYYY-MM-DD)
   */
  @action
  fetchSwapList(params = {}) {
    this.isFetching = true;
    const queryParams = {};
    if (params.start_date) queryParams.start_date = params.start_date;
    if (params.end_date) queryParams.end_date = params.end_date;

    return http.get('/api/schedule/swap/', { params: queryParams })
      .then(res => {
        this.swapList = res;
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 显示换班表单
   * @param {Object} info - 表单初始数据
   */
  @action
  showForm(info = {}) {
    this.formVisible = true;
    this.record = info;
  }

  /**
   * 关闭表单
   */
  @action
  hideForm() {
    this.formVisible = false;
    this.record = {};
  }

  /**
   * 创建换班申请
   * @param {Object} data - 换班数据
   */
  @action
  createSwap(data) {
    this.isFetching = true;
    return http.post('/api/schedule/swap/', data)
      .then(() => {
        return this.fetchSwapList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 审批通过换班
   * @param {number} id - 换班ID
   * @param {string} remarks - 审批备注
   */
  @action
  approveSwap(id, remarks = '') {
    this.isFetching = true;
    return http.patch('/api/schedule/swap/', {
      id,
      status: 'approved',
      remarks
    })
      .then(() => {
        return this.fetchSwapList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 拒绝换班
   * @param {number} id - 换班ID
   * @param {string} remarks - 拒绝原因
   */
  @action
  rejectSwap(id, remarks = '') {
    this.isFetching = true;
    return http.patch('/api/schedule/swap/', {
      id,
      status: 'rejected',
      remarks
    })
      .then(() => {
        return this.fetchSwapList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 撤销换班
   * @param {number} id - 换班ID
   * @param {boolean} cancelSwap - 是否恢复原排班
   */
  @action
  cancelSwap(id, cancelSwap = false) {
    this.isFetching = true;
    return http.patch('/api/schedule/swap/', {
      id,
      status: 'cancelled',
      cancel_swap: cancelSwap
    })
      .then(() => {
        return this.fetchSwapList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 删除换班记录
   * @param {number} id - 换班ID
   */
  @action
  deleteSwap(id) {
    this.isFetching = true;
    return http.delete('/api/schedule/swap/', { params: { id } })
      .then(() => {
        return this.fetchSwapList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 批量创建换班
   * @param {Array} records - 换班记录列表
   */
  @action
  batchCreateSwap(records) {
    this.isFetching = true;
    return http.post('/api/schedule/batch_swap/', { records })
      .then(() => {
        return this.fetchSwapList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 检查某排班是否涉及换班
   * @param {Object} schedule - 排班对象
   */
  isInSwap(schedule) {
    if (!schedule) return false;
    return this.swapList.some(swap =>
      swap.status === 'approved' &&
      (swap.from_date === schedule.schedule_date || swap.to_date === schedule.schedule_date) &&
      (swap.from_staff_id === schedule.staff_id || swap.to_staff_id === schedule.staff_id)
    );
  }

  /**
   * 根据ID获取换班记录
   * @param {number} id - 换班ID
   */
  getSwapById(id) {
    return this.swapList.find(s => s.id === id);
  }

  /**
   * 获取指定人员的换班记录
   * @param {number} staffId - 人员ID
   */
  getSwapsByStaffId(staffId) {
    return this.swapList.filter(s =>
      s.from_staff_id === staffId || s.to_staff_id === staffId
    );
  }

  /**
   * 获取指定日期的换班记录
   * @param {string} dateStr - 日期字符串
   */
  getSwapsByDate(dateStr) {
    return this.swapList.filter(s =>
      s.from_date === dateStr || s.to_date === dateStr
    );
  }

  /**
   * 获取待审批的换班列表
   */
  getPendingSwaps() {
    return this.swapList.filter(s => s.status === 'pending');
  }

  /**
   * 获取换班统计
   */
  getSwapStats() {
    const stats = {
      total: this.swapList.length,
      pending: 0,
      approved: 0,
      rejected: 0,
      cancelled: 0
    };
    this.swapList.forEach(s => {
      if (stats[s.status] !== undefined) {
        stats[s.status]++;
      }
    });
    return stats;
  }
}

export default new SwapStore();
