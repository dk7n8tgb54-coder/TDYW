/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 排班数据管理Store
 * 
 * 职责：
 * - 排班列表管理
 * - 日历日期管理
 * - 排班CRUD操作
 * - 批量操作
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import moment from 'moment';

class ScheduleStore {
  @observable scheduleList = [];
  @observable isFetching = false;
  @observable formVisible = false;
  @observable record = {};
  @observable currentDate = moment();
  @observable selectedDate = null;
  @observable selectedCellData = null;
  @observable isInitialized = false; // 修复P0-1：添加初始化状态标记

  /**
   * 获取排班列表
   * @param {number} year - 年份
   * @param {number} month - 月份（1-12）
   * @param {boolean} append - 是否追加数据（默认true）
   */
  @action
  fetchSchedule(year, month, append = true) {
    console.log(`[ScheduleStore] fetchSchedule 被调用: year=${year}, month=${month}, append=${append}`);
    this.isFetching = true;
    return http.get('/api/schedule/', { params: { year, month } })
      .then(res => {
        console.log(`[ScheduleStore] fetchSchedule 成功，获取 ${res.length} 条数据`);
        if (append) {
          // 合并数据，避免重复
          const existingIds = new Set(this.scheduleList.map(s => s.id));
          const newSchedules = res.filter(s => !existingIds.has(s.id));
          this.scheduleList = [...this.scheduleList, ...newSchedules];
        } else {
          // 直接覆盖
          this.scheduleList = res;
        }
      })
      .catch(error => {
        console.error(`[ScheduleStore] fetchSchedule 失败:`, error);
        throw error;
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 设置当前日期
   * @param {moment|Date|string} date - 日期
   */
  @action
  setCurrentDate(date) {
    this.currentDate = moment(date);
  }

  /**
   * 显示排班表单
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
   * 处理日历单元格点击
   * @param {string} date - 日期字符串
   * @param {Array} cellData - 单元格数据
   */
  @action
  handleCellClick(date, cellData) {
    this.selectedDate = date;
    this.selectedCellData = cellData;
  }

  /**
   * 添加排班
   * @param {Object} data - 排班数据
   */
  @action
  addSchedule(data) {
    this.isFetching = true;
    return http.post('/api/schedule/', data)
      .then(() => {
        return this.fetchSchedule(this.currentDate.year(), this.currentDate.month() + 1);
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 删除排班
   * @param {number} id - 排班ID
   */
  @action
  deleteSchedule(id) {
    this.isFetching = true;
    return http.delete('/api/schedule/', { params: { id } })
      .then(() => {
        return this.fetchSchedule(this.currentDate.year(), this.currentDate.month() + 1);
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 删除排班但不刷新（用于批量删除）
   * @param {number} id - 排班ID
   */
  @action
  deleteScheduleNoRefresh(id) {
    return http.delete('/api/schedule/', { params: { id } });
  }

  /**
   * 自动排班
   * @param {Object} params - 排班参数
   */
  @action
  autoSchedule(params) {
    this.isFetching = true;
    return http.post('/api/schedule/auto/', params)
      .then(() => {
        return this.fetchSchedule(this.currentDate.year(), this.currentDate.month() + 1);
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 批量调整排班
   * @param {Array} adjustments - 调整列表
   */
  @action
  batchAdjustSchedule(adjustments) {
    this.isFetching = true;
    return http.post('/api/schedule/batch_adjust/', { adjustments })
      .then(() => {
        return this.fetchSchedule(
          this.currentDate.year(),
          this.currentDate.month() + 1,
          false
        );
      })
      .finally(() => this.isFetching = false);
  }

  /**
   * 批量查询排班（用于批量删除预览）
   * @param {Array} staff_ids - 人员ID列表
   * @param {string} start_date - 开始日期
   * @param {string} end_date - 结束日期
   */
  @action
  batchQuerySchedules(staff_ids, start_date, end_date) {
    this.isFetching = true;
    return http.post('/api/schedule/batch_query/', {
      staff_ids,
      start_date,
      end_date
    }).finally(() => this.isFetching = false);
  }

  /**
   * 刷新当前月份的排班
   */
  @action
  refreshCurrentMonth() {
    return this.fetchSchedule(
      this.currentDate.year(),
      this.currentDate.month() + 1,
      false
    );
  }

  /**
   * 根据ID获取排班
   * @param {number} id - 排班ID
   */
  getScheduleById(id) {
    return this.scheduleList.find(s => s.id === id);
  }

  /**
   * 根据日期获取排班列表
   * @param {string} dateStr - 日期字符串 YYYY-MM-DD
   */
  getSchedulesByDate(dateStr) {
    return this.scheduleList.filter(s => s.schedule_date === dateStr);
  }

  /**
   * 检查某日期是否有排班
   * @param {string} dateStr - 日期字符串
   * @param {number} staffId - 人员ID（可选）
   */
  hasSchedule(dateStr, staffId = null) {
    if (staffId) {
      return this.scheduleList.some(
        s => s.schedule_date === dateStr && s.staff_id === staffId
      );
    }
    return this.scheduleList.some(s => s.schedule_date === dateStr);
  }

  /**
   * 设置初始化状态（修复P0-1竞态条件）
   * @param {boolean} value - 初始化状态
   */
  @action
  setInitialized(value) {
    console.log(`[ScheduleStore] setInitialized 被调用: ${value}, 当前值: ${this.isInitialized}`);
    this.isInitialized = value;
    console.log(`[ScheduleStore] setInitialized 完成，新值: ${this.isInitialized}`);
  }

  /**
   * 批量删除排班 - 修复P0-2：使用批量删除API+事务保护
   * @param {Array<number>} ids - 排班ID列表
   * @returns {Promise<Object>} 删除结果
   */
  @action
  batchDeleteSchedules(ids) {
    this.isFetching = true;
    return http.post('/api/schedule/batch_delete/', { ids })
      .then(result => {
        // 删除成功后刷新当前月份数据
        return this.fetchSchedule(
          this.currentDate.year(),
          this.currentDate.month() + 1,
          false
        ).then(() => result);
      })
      .finally(() => this.isFetching = false);
  }
}

export default new ScheduleStore();
