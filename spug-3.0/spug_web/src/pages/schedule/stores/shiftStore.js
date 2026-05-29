/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 班次数据管理Store
 * 
 * 职责：
 * - 班次列表管理
 * - 班次CRUD操作
 */
import { observable, action } from 'mobx';
import { http } from 'libs';

class ShiftStore {
  @observable shiftList = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};

  /**
   * 获取班次列表
   */
  @action
  fetchShiftList() {
    this.isFetching = true;
    return http.get('/api/schedule/shift/')
      .then(res => {
        this.shiftList = res;
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 显示班次表单
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
   * 创建班次
   * @param {Object} data - 班次数据
   */
  @action
  createShift(data) {
    this.isFetching = true;
    return http.post('/api/schedule/shift/', data)
      .then(() => {
        return this.fetchShiftList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 更新班次
   * @param {Object} data - 班次数据
   */
  @action
  updateShift(data) {
    this.isFetching = true;
    return http.post('/api/schedule/shift/', data)
      .then(() => {
        return this.fetchShiftList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 删除班次
   * @param {number} id - 班次ID
   */
  @action
  deleteShift(id) {
    this.isFetching = true;
    return http.delete('/api/schedule/shift/', { params: { id } })
      .then(() => {
        return this.fetchShiftList();
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 根据ID获取班次
   * @param {number} id - 班次ID
   */
  getShiftById(id) {
    return this.shiftList.find(s => s.id === id);
  }

  /**
   * 获取默认班次
   */
  getDefaultShift() {
    return this.shiftList.find(s => s.is_default);
  }

  /**
   * 获取班次类型显示文本
   * @param {Object} shift - 班次对象
   */
  getShiftTypeText(shift) {
    if (!shift) return '';
    if (shift.shift_type === 'work_rest' && shift.work_days && shift.rest_days) {
      return `上${shift.work_days}休${shift.rest_days}`;
    }
    return '自定义';
  }

  /**
   * 检查班次是否存在
   * @param {number} id - 班次ID
   */
  hasShift(id) {
    return this.shiftList.some(s => s.id === id);
  }
}

export default new ShiftStore();
