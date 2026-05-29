/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 排班数据Hook
 * 
 * 封装排班数据的获取、筛选和计算逻辑
 */
import { useEffect, useCallback, useMemo } from 'react';
import moment from 'moment';
import store from '../stores';

/**
 * 获取指定日期的排班列表
 * @param {Array} scheduleList - 排班列表
 * @param {moment|Date|string} date - 日期
 * @returns {Array} 该日期的排班列表
 */
export function useSchedulesForDate(scheduleList, date) {
  return useMemo(() => {
    const dateStr = moment(date).format('YYYY-MM-DD');
    return scheduleList.filter(s => s.schedule_date === dateStr);
  }, [scheduleList, date]);
}

/**
 * 获取按班次分组的排班
 * @param {Array} schedules - 排班列表
 * @returns {Object} 按班次ID分组的排班
 */
export function useGroupedByShift(schedules) {
  return useMemo(() => {
    const groups = {};
    schedules.forEach(schedule => {
      const shiftId = schedule.shift_id || 0;
      if (!groups[shiftId]) {
        groups[shiftId] = {
          shift_name: schedule.shift_name,
          shift_color: schedule.shift_color,
          schedules: []
        };
      }
      groups[shiftId].schedules.push(schedule);
    });
    return groups;
  }, [schedules]);
}

/**
 * 检查排班是否涉及换班
 * @param {Object} schedule - 排班对象
 * @param {Array} swapList - 换班列表
 * @returns {boolean}
 */
export function useIsInSwap(schedule, swapList) {
  return useMemo(() => {
    if (!swapList || swapList.length === 0) return false;
    
    return swapList.some(swap => {
      const isApproved = swap.status === 'approved';
      const isSameDate = swap.from_date === schedule.schedule_date || 
                        swap.to_date === schedule.schedule_date;
      const isSameStaff = swap.from_staff_id === schedule.staff_id || 
                         swap.to_staff_id === schedule.staff_id;
      return isApproved && isSameDate && isSameStaff;
    });
  }, [schedule, swapList]);
}

/**
 * 检查排班是否涉及替班
 * @param {Object} schedule - 排班对象
 * @param {Array} substituteList - 替班列表
 * @returns {boolean}
 */
export function useIsInSubstitute(schedule, substituteList) {
  return useMemo(() => {
    if (!substituteList || substituteList.length === 0) return false;
    
    return substituteList.some(sub => {
      const isApproved = sub.status === 'approved';
      const isSameDate = sub.schedule_date === schedule.schedule_date;
      const isSameStaff = sub.original_staff_id === schedule.staff_id || 
                         sub.substitute_staff_id === schedule.staff_id;
      return isApproved && isSameDate && isSameStaff;
    });
  }, [schedule, substituteList]);
}

/**
 * 初始化排班数据
 * 在组件挂载时获取基础数据
 */
export function useScheduleInit() {
  useEffect(() => {
    store.fetchStaffList();
    store.fetchShiftList();
    store.fetchSwapList();
    store.fetchSubstituteList();
  }, []);
}

/**
 * 获取扩展月份数据（当前月+前后月）
 * @param {moment} date - 基准日期
 */
export function useFetchExtendedSchedules(date) {
  const fetchData = useCallback(async () => {
    const monthsToFetch = [];
    
    // 上个月
    const prevMonth = date.clone().subtract(1, 'month');
    monthsToFetch.push({ 
      year: prevMonth.year(), 
      month: prevMonth.month() + 1 
    });
    
    // 当前月
    monthsToFetch.push({ 
      year: date.year(), 
      month: date.month() + 1 
    });
    
    // 下个月
    const nextMonth = date.clone().add(1, 'month');
    monthsToFetch.push({ 
      year: nextMonth.year(), 
      month: nextMonth.month() + 1 
    });
    
    // 去重并获取数据
    const uniqueMonths = Array.from(
      new Set(monthsToFetch.map(m => `${m.year}-${m.month}`))
    );
    
    for (let i = 0; i < uniqueMonths.length; i++) {
      const [y, m] = uniqueMonths[i].split('-').map(Number);
      await store.fetchSchedule(y, m, i > 0);
    }
  }, [date]);

  return fetchData;
}

export default {
  useSchedulesForDate,
  useGroupedByShift,
  useIsInSwap,
  useIsInSubstitute,
  useScheduleInit,
  useFetchExtendedSchedules
};
