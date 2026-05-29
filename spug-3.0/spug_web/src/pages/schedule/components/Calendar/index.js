/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 日历视图组件（重构后）
 * 
 * 第4阶段重构：拆分自原CalendarView.js
 * 
 * 子组件：
 * - DateCell: 日期单元格渲染
 * 
 * 依赖：
 * - ScheduleModal: 排班管理弹窗
 * - BatchDeleteModal: 批量删除弹窗
 * - hooks/useSchedule: 数据获取和处理
 */
import React, { useState, useEffect, useCallback } from 'react';
import { observer } from 'mobx-react';
import { Calendar } from 'antd';
import moment from 'moment';
import store from '../../stores';
import { useFetchExtendedSchedules } from '../../hooks';
import DateCell from './DateCell';
import ScheduleModal from '../ScheduleModal';
import BatchDeleteModal from '../BatchDeleteModal';

function CalendarView({ currentDate, scheduleList, onDateChange }) {
  // ===== 状态管理 =====
  const [internalDate, setInternalDate] = useState(
    moment.isMoment(currentDate) ? currentDate : moment(currentDate)
  );
  const [calendarMode, setCalendarMode] = useState('month');
  
  // 排班弹窗状态
  const [scheduleModalVisible, setScheduleModalVisible] = useState(false);
  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedSchedules, setSelectedSchedules] = useState([]);
  
  // 批量删除弹窗状态
  const [batchDeleteModalVisible, setBatchDeleteModalVisible] = useState(false);

  // 修复P0-1：移除useScheduleInit调用，避免重复初始化
  // 数据初始化由父组件统一处理

  // ===== 监听外部日期变化 =====
  useEffect(() => {
    const newMomentValue = moment.isMoment(currentDate) 
      ? currentDate 
      : moment(currentDate);
    if (!internalDate.isSame(newMomentValue)) {
      setInternalDate(newMomentValue);
    }
  }, [currentDate, internalDate]);

  // ===== 获取扩展排班数据（仅当日期真正改变时）=====
  const fetchExtendedScheduleData = useFetchExtendedSchedules(internalDate);
  
  // 修复P0-1：移除setTimeout临时解决方案
  // 只在日期改变且store已完成初始化时获取数据
  useEffect(() => {
    // 确保store已初始化且不是初始渲染
    if (store.isInitialized && internalDate) {
      fetchExtendedScheduleData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [internalDate, store.isInitialized]);

  // ===== 监听批量删除事件 =====
  useEffect(() => {
    const handleOpenBatchDelete = () => {
      setBatchDeleteModalVisible(true);
    };
    window.addEventListener('openBatchDelete', handleOpenBatchDelete);
    return () => {
      window.removeEventListener('openBatchDelete', handleOpenBatchDelete);
    };
  }, []);

  // ===== 日期单元格渲染 =====
  const dateCellRender = useCallback((value) => {
    const dateStr = moment(value).format('YYYY-MM-DD');
    const schedules = scheduleList.filter(s => s.schedule_date === dateStr);
    
    // 标记换班/替班状态
    const schedulesWithStatus = schedules.map(schedule => ({
      ...schedule,
      isSwap: store.isInSwap(schedule),
      isSubstitute: store.isInSubstitute(schedule)
    }));

    const handleCellClick = (dateStr, cellSchedules) => {
      setSelectedDate(dateStr);
      setSelectedSchedules(cellSchedules);
      setScheduleModalVisible(true);
    };

    return (
      <DateCell
        value={value}
        schedules={schedulesWithStatus}
        internalDate={internalDate}
        onClick={handleCellClick}
      />
    );
  }, [scheduleList, internalDate]);

  // ===== 日历面板变化处理 =====
  const handlePanelChange = useCallback((date, mode) => {
    setCalendarMode(mode);
    setInternalDate(date);
    
    if (onDateChange) {
      onDateChange(date);
    }
    
    if (mode === 'month') {
      fetchExtendedScheduleData();
    }
  }, [onDateChange, fetchExtendedScheduleData]);

  // ===== 排班操作成功回调 =====
  const handleScheduleSuccess = useCallback(() => {
    fetchExtendedScheduleData();
  }, [fetchExtendedScheduleData]);

  // ===== 关闭弹窗 =====
  const handleCloseScheduleModal = useCallback(() => {
    setScheduleModalVisible(false);
    setSelectedSchedules([]);
  }, []);

  const handleCloseBatchDeleteModal = useCallback(() => {
    setBatchDeleteModalVisible(false);
  }, []);

  return (
    <>
      <Calendar
        mode={calendarMode}
        onPanelChange={handlePanelChange}
        dateCellRender={dateCellRender}
      />

      <ScheduleModal
        visible={scheduleModalVisible}
        selectedDate={selectedDate}
        selectedSchedules={selectedSchedules}
        onClose={handleCloseScheduleModal}
        onSuccess={handleScheduleSuccess}
      />

      <BatchDeleteModal
        visible={batchDeleteModalVisible}
        onClose={handleCloseBatchDeleteModal}
        onSuccess={handleScheduleSuccess}
      />
    </>
  );
}

export default observer(CalendarView);
