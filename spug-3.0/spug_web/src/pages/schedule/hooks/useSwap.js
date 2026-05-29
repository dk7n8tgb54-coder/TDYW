/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 换班管理自定义 Hook
 */
import { useState, useEffect, useCallback } from 'react';
import { message } from 'antd';
import { http } from 'libs';
import moment from 'moment';

export function useSwap(store) {
  const [fromStaffSchedules, setFromStaffSchedules] = useState([]);
  const [toStaffSchedules, setToStaffSchedules] = useState([]);
  const [fromDate, setFromDate] = useState(null);
  const [toDate, setToDate] = useState(null);
  const [filterDates, setFilterDates] = useState(() => {
    const now = moment();
    return [now.clone().startOf('month'), now.clone().endOf('month')];
  });

  const fetchSwapData = useCallback(() => {
    const params = {};
    if (filterDates[0]) params.start_date = filterDates[0].format('YYYY-MM-DD');
    if (filterDates[1]) params.end_date = filterDates[1].format('YYYY-MM-DD');
    store.fetchSwapList(params);
  }, [filterDates, store]);

  useEffect(() => {
    fetchSwapData();
    store.fetchSchedule(store.currentDate.year(), store.currentDate.month() + 1);
  }, []);

  const handleFilterDateChange = (dates) => setFilterDates(dates || [null, null]);
  const handleSearch = () => fetchSwapData();

  const handleReset = () => {
    const now = moment();
    setFilterDates([now.clone().startOf('month'), now.clone().endOf('month')]);
    store.fetchSwapList({
      start_date: now.format('YYYY-MM-01'),
      end_date: now.endOf('month').format('YYYY-MM-DD')
    });
  };

  const handleFromDateChange = (dateStr) => {
    setFromDate(dateStr);
    if (dateStr) {
      setFromStaffSchedules(store.scheduleList.filter(s => s.schedule_date === dateStr));
    } else {
      setFromStaffSchedules([]);
    }
  };

  const handleToDateChange = (dateStr) => {
    setToDate(dateStr);
    if (dateStr) {
      setToStaffSchedules(store.scheduleList.filter(s => s.schedule_date === dateStr));
    } else {
      setToStaffSchedules([]);
    }
  };

  const handleAddSwap = async (form, values) => {
    try {
      const from_date_str = values.from_date ? moment(values.from_date).format('YYYY-MM-DD') : '';
      const to_date_str = values.to_date ? moment(values.to_date).format('YYYY-MM-DD') : '';

      if (!from_date_str || !to_date_str) {
        message.warning('请选择换出和换入日期');
        return false;
      }

      const postData = {
        from_staff_id: values.from_staff_id,
        from_staff_name: store.staffList.find(s => s.id === values.from_staff_id)?.user_name || '',
        to_staff_id: values.to_staff_id,
        to_staff_name: store.staffList.find(s => s.id === values.to_staff_id)?.user_name || '',
        from_date: from_date_str,
        to_date: to_date_str,
        from_shift_id: values.from_shift_id,
        to_shift_id: values.to_shift_id,
        reason: values.reason || ''
      };

      await http.post('/api/schedule/swap/', postData);
      message.success('换班申请提交成功');
      fetchSwapData();
      store.fetchSchedule(store.currentDate.year(), store.currentDate.month() + 1);
      return true;
    } catch (error) {
      console.error('Failed to add swap:', error);
      return false;
    }
  };

  const resetForm = (form) => {
    store.swapFormVisible = false;
    form.resetFields();
    setFromDate(null);
    setToDate(null);
    setFromStaffSchedules([]);
    setToStaffSchedules([]);
  };

  return {
    fromStaffSchedules,
    toStaffSchedules,
    fromDate,
    toDate,
    filterDates,
    handleFilterDateChange,
    handleSearch,
    handleReset,
    handleFromDateChange,
    handleToDateChange,
    handleAddSwap,
    resetForm
  };
}
