/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 替班数据管理Store
 * 
 * 职责：
 * - 替班列表管理
 * - 替班CRUD操作
 * - 替班审批流程
 * - 批量替班
 */
import { observable, action } from 'mobx';
import { http } from 'libs';

class SubstituteStore {
  @observable substituteList = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};

  /**
   * 获取替班列表
   * @param {Object} params - 查询参数
   * @param {string} params.start_date - 开始日期 (YYYY-MM-DD)
   * @param {string} params.end_date - 结束日期 (YYYY-MM-DD)
   */
  @action
  fetchSubstituteList(params = {}) {
    this.isFetching = true;
    const queryParams = {};
    if (params.start_date) queryParams.start_date = params.start_date;
    if (params.end_date) queryParams.end_date = params.end_date;

    return http.get('/api/schedule/substitute/', { params: queryParams })
      .then(res => {
        this.substituteList = res;
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 显示替班表单
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
   * 创建替班申请
   * @param {Object} data - 替班数据
   */
  @action
  createSubstitute(data) {
    this.isFetching = true;
    return http.post('/api/schedule/substitute/', data)
      .then(() => {
        return this.fetchSubstituteList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 审批通过替班
   * @param {number} id - 替班ID
   * @param {string} remarks - 审批备注
   */
  @action
  approveSubstitute(id, remarks = '') {
    this.isFetching = true;
    return http.patch('/api/schedule/substitute/', {
      id,
      status: 'approved',
      remarks
    })
      .then(() => {
        return this.fetchSubstituteList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 拒绝替班
   * @param {number} id - 替班ID
   * @param {string} remarks - 拒绝原因
   */
  @action
  rejectSubstitute(id, remarks = '') {
    this.isFetching = true;
    return http.patch('/api/schedule/substitute/', {
      id,
      status: 'rejected',
      remarks
    })
      .then(() => {
        return this.fetchSubstituteList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 撤销替班
   * @param {number} id - 替班ID
   */
  @action
  cancelSubstitute(id) {
    this.isFetching = true;
    return http.patch('/api/schedule/substitute/', {
      id,
      status: 'cancelled'
    })
      .then(() => {
        return this.fetchSubstituteList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 删除替班记录
   * @param {number} id - 替班ID
   */
  @action
  deleteSubstitute(id) {
    this.isFetching = true;
    return http.delete('/api/schedule/substitute/', { params: { id } })
      .then(() => {
        return this.fetchSubstituteList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 批量创建替班
   * @param {Array} records - 替班记录列表
   */
  @action
  batchCreateSubstitute(records) {
    this.isFetching = true;
    return http.post('/api/schedule/batch_substitute/', { records })
      .then(() => {
        return this.fetchSubstituteList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 检查某排班是否涉及替班
   * @param {Object} schedule - 排班对象
   */
  isInSubstitute(schedule) {
    if (!schedule) return false;
    return this.substituteList.some(sub =>
      sub.status === 'approved' &&
      sub.schedule_date === schedule.schedule_date &&
      (sub.original_staff_id === schedule.staff_id || sub.substitute_staff_id === schedule.staff_id)
    );
  }

  /**
   * 根据ID获取替班记录
   * @param {number} id - 替班ID
   */
  getSubstituteById(id) {
    return this.substituteList.find(s => s.id === id);
  }

  /**
   * 获取指定人员的替班记录（作为原值班人或替班人）
   * @param {number} staffId - 人员ID
   */
  getSubstitutesByStaffId(staffId) {
    return this.substituteList.filter(s =>
      s.original_staff_id === staffId || s.substitute_staff_id === staffId
    );
  }

  /**
   * 获取指定日期的替班记录
   * @param {string} dateStr - 日期字符串
   */
  getSubstitutesByDate(dateStr) {
    return this.substituteList.filter(s => s.schedule_date === dateStr);
  }

  /**
   * 获取待审批的替班列表
   */
  getPendingSubstitutes() {
    return this.substituteList.filter(s => s.status === 'pending');
  }

  /**
   * 获取替班统计
   */
  getSubstituteStats() {
    const stats = {
      total: this.substituteList.length,
      pending: 0,
      approved: 0,
      rejected: 0,
      cancelled: 0
    };
    this.substituteList.forEach(s => {
      if (stats[s.status] !== undefined) {
        stats[s.status]++;
      }
    });
    return stats;
  }
}

export default new SubstituteStore();
