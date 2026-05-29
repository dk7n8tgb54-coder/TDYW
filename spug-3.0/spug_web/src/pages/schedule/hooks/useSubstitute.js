/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 替班管理自定义 Hook
 */
import { useState, useEffect, useCallback } from 'react';
import { message } from 'antd';
import { http } from 'libs';
import moment from 'moment';

export function useSubstitute(store) {
  const [dateSchedules, setDateSchedules] = useState([]);
  const [selectedDate, setSelectedDate] = useState(null);
  const [filterDates, setFilterDates] = useState(() => {
    const now = moment();
    return [now.clone().startOf('month'), now.clone().endOf('month')];
  });

  const fetchSubstituteData = useCallback(() => {
    const params = {};
    if (filterDates[0]) {
      params.start_date = filterDates[0].format('YYYY-MM-DD');
    }
    if (filterDates[1]) {
      params.end_date = filterDates[1].format('YYYY-MM-DD');
    }
    store.fetchSubstituteList(params);
  }, [filterDates, store]);

  useEffect(() => {
    fetchSubstituteData();
    store.fetchSchedule(store.currentDate.year(), store.currentDate.month() + 1);
  }, []);

  const handleFilterDateChange = (dates) => {
    setFilterDates(dates || [null, null]);
  };

  const handleSearch = () => {
    fetchSubstituteData();
  };

  const handleReset = () => {
    const now = moment();
    setFilterDates([now.clone().startOf('month'), now.clone().endOf('month')]);
    store.fetchSubstituteList({
      start_date: now.format('YYYY-MM-01'),
      end_date: now.endOf('month').format('YYYY-MM-DD')
    });
  };

  const handleDateChange = (dateStr) => {
    setSelectedDate(dateStr);
    if (dateStr) {
      const daySchedules = store.scheduleList.filter(s => s.schedule_date === dateStr);
      setDateSchedules(daySchedules);
    } else {
      setDateSchedules([]);
    }
  };

  const handleAddSubstitute = async (form, values) => {
    try {
      const date_str = values.date ? moment(values.date).format('YYYY-MM-DD') : '';

      if (!date_str) {
        message.warning('请选择替班日期');
        return false;
      }

      const postData = {
        original_staff_id: values.original_staff_id,
        original_staff_name: store.staffList.find(s => s.id === values.original_staff_id)?.user_name || '',
        substitute_staff_id: values.substitute_staff_id,
        substitute_staff_name: store.staffList.find(s => s.id === values.substitute_staff_id)?.user_name || '',
        schedule_date: date_str,
        shift_id: values.shift_id,
        shift_name: values.shift_name,
        reason: values.reason || ''
      };

      await http.post('/api/schedule/substitute/', postData);
      message.success('替班申请提交成功');
      fetchSubstituteData();
      store.fetchSchedule(store.currentDate.year(), store.currentDate.month() + 1);
      return true;
    } catch (error) {
      console.error('Failed to add substitute:', error);
      return false;
    }
  };

  const resetForm = (form) => {
    store.substituteFormVisible = false;
    form.resetFields();
    setSelectedDate(null);
    setDateSchedules([]);
  };

  return {
    dateSchedules,
    selectedDate,
    filterDates,
    setFilterDates,
    handleFilterDateChange,
    handleSearch,
    handleReset,
    handleDateChange,
    handleAddSubstitute,
    resetForm
  };
}
