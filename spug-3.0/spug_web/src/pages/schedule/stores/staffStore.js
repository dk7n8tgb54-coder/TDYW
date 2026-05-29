/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 人员数据管理Store
 * 
 * 职责：
 * - 排班人员列表管理
 * - 人员CRUD操作
 */
import { observable, action } from 'mobx';
import { http } from 'libs';

class StaffStore {
  @observable staffList = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};

  /**
   * 获取人员列表
   */
  @action
  fetchStaffList() {
    this.isFetching = true;
    return http.get('/api/schedule/staff/')
      .then(res => {
        this.staffList = res;
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 显示人员表单
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
   * 创建人员
   * @param {Object} data - 人员数据
   */
  @action
  createStaff(data) {
    this.isFetching = true;
    return http.post('/api/schedule/staff/', data)
      .then(() => {
        return this.fetchStaffList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 更新人员
   * @param {Object} data - 人员数据
   */
  @action
  updateStaff(data) {
    this.isFetching = true;
    return http.post('/api/schedule/staff/', data)
      .then(() => {
        return this.fetchStaffList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 更新人员状态（启用/禁用）
   * @param {number} id - 人员ID
   * @param {boolean} isActive - 是否启用
   */
  @action
  updateStaffStatus(id, isActive) {
    this.isFetching = true;
    return http.patch('/api/schedule/staff/', { id, is_active: isActive })
      .then(() => {
        return this.fetchStaffList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 根据ID获取人员
   * @param {number} id - 人员ID
   */
  getStaffById(id) {
    return this.staffList.find(s => s.id === id);
  }

  /**
   * 根据名称获取人员
   * @param {string} name - 人员名称
   */
  getStaffByName(name) {
    return this.staffList.find(s => s.user_name === name);
  }

  /**
   * 获取启用状态的人员列表
   */
  getActiveStaffList() {
    return this.staffList.filter(s => s.is_active);
  }

  /**
   * 检查人员是否存在
   * @param {number} id - 人员ID
   */
  hasStaff(id) {
    return this.staffList.some(s => s.id === id);
  }
}

export default new StaffStore();
