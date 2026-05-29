/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 排班管理弹窗组件
 * 
 * 组合：
 * - ExistingSchedules: 已有排班列表
 * - ScheduleForm: 添加排班表单
 */
import React from 'react';
import { Modal, Form, Button, Space, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import moment from 'moment';
import store from '../../stores';
import ExistingSchedules from './ExistingSchedules';
import ScheduleForm from './ScheduleForm';

function ScheduleModal({
  visible,
  selectedDate,
  selectedSchedules,
  onClose,
  onSuccess
}) {
  const [form] = Form.useForm();
  const [autoSchedule, setAutoSchedule] = React.useState(false);
  const [autoDateRange, setAutoDateRange] = React.useState([]);
  const [checkedIds, setCheckedIds] = React.useState([]);
  const [selectAll, setSelectAll] = React.useState(false);

  // 重置状态当弹窗打开时
  React.useEffect(() => {
    if (visible) {
      setCheckedIds([]);
      setSelectAll(false);
      setAutoSchedule(false);
      setAutoDateRange([]);
      form.resetFields();
    }
  }, [visible, form]);

  // 生成自动排班数据
  const generateAutoSchedules = (staff, shift, startDate, endDate) => {
    const schedules = [];

    if (shift.shift_type === 'work_rest' && shift.work_days && shift.rest_days) {
      // 上X休Y模式
      let currentDate = startDate.clone();
      let workCount = 0;
      let restCount = 0;
      let isInWorkCycle = true;

      while (currentDate.isSameOrBefore(endDate)) {
        if (isInWorkCycle) {
          schedules.push({
            staff_id: staff.id,
            staff_name: staff.user_name,
            schedule_date: currentDate.format('YYYY-MM-DD'),
            shift_id: shift.id,
            shift_name: shift.name,
          });
          workCount++;
          if (workCount >= shift.work_days) {
            workCount = 0;
            isInWorkCycle = false;
          }
        } else {
          restCount++;
          if (restCount >= shift.rest_days) {
            restCount = 0;
            isInWorkCycle = true;
          }
        }
        currentDate.add(1, 'day');
      }
    } else {
      // 自定义模式 - 每天都排班
      let currentDate = startDate.clone();
      while (currentDate.isSameOrBefore(endDate)) {
        schedules.push({
          staff_id: staff.id,
          staff_name: staff.user_name,
          schedule_date: currentDate.format('YYYY-MM-DD'),
          shift_id: shift.id,
          shift_name: shift.name,
        });
        currentDate.add(1, 'day');
      }
    }

    return schedules;
  };

  // 检查排班冲突
  const checkConflicts = (schedules) => {
    const scheduleList = store.scheduleList;
    const conflictingDates = [];
    
    for (const schedule of schedules) {
      const existing = scheduleList.find(s =>
        s.schedule_date === schedule.schedule_date && s.staff_id === schedule.staff_id
      );
      if (existing) {
        conflictingDates.push(schedule.schedule_date);
      }
    }
    
    return conflictingDates;
  };

  // 处理添加排班
  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      const staff = store.staffList.find(s => s.id === values.staff_id);
      const shift = store.shiftList.find(s => s.id === values.shift_id);

      if (!staff || !shift) {
        message.error('请选择人员和班次');
        return;
      }

      if (autoSchedule && values.auto_date_range && values.auto_date_range.length === 2) {
        // 自动排班模式
        const startDate = moment(values.auto_date_range[0]);
        const endDate = moment(values.auto_date_range[1]);
        const schedules = generateAutoSchedules(staff, shift, startDate, endDate);

        // 检查冲突
        const conflicts = checkConflicts(schedules);
        if (conflicts.length > 0) {
          message.warning(`以下日期该人员已有排班：${conflicts.join(', ')}`);
          return;
        }

        // 批量添加
        for (const schedule of schedules) {
          await store.addSchedule({
            ...schedule,
            notes: values.notes || ''
          });
        }
        message.success(`已自动排班 ${schedules.length} 天`);
      } else {
        // 单日排班模式
        const existing = store.scheduleList.find(s =>
          s.schedule_date === selectedDate && s.staff_id === staff.id
        );
        if (existing) {
          message.error('该人员在此日期已有排班');
          return;
        }

        await store.addSchedule({
          staff_id: staff.id,
          staff_name: staff.user_name,
          schedule_date: selectedDate,
          shift_id: shift.id,
          shift_name: shift.name,
          notes: values.notes || '',
        });
        message.success('添加排班成功');
      }

      onSuccess();
      onClose();
      form.resetFields();
      setAutoSchedule(false);
    } catch (error) {
      console.error('Failed to add schedule:', error);
    }
  };

  // 处理单条删除
  const handleDelete = async (id) => {
    try {
      await store.deleteSchedule(id);
      message.success('删除排班成功');
      onSuccess();
      onClose();
    } catch (error) {
      console.error('Failed to delete schedule:', error);
    }
  };

  // 处理批量删除 - 修复P0-2：使用批量删除API+事务保护
  const handleBatchDelete = async () => {
    if (checkedIds.length === 0) {
      message.warning('请先选择要删除的排班');
      return;
    }

    try {
      // 使用新的批量删除API，带事务保护
      const result = await store.batchDeleteSchedules(checkedIds);
      message.success(`已删除 ${result.deleted_count} 条排班记录`);
      onSuccess();
      onClose();
      setCheckedIds([]);
      setSelectAll(false);
    } catch (error) {
      console.error('Failed to batch delete:', error);
      message.error(error.message || '批量删除失败，请重试');
    }
  };

  // 处理单个选择变化
  const handleCheckChange = (id, checked) => {
    const newCheckedIds = checked
      ? [...checkedIds, id]
      : checkedIds.filter(checkedId => checkedId !== id);
    setCheckedIds(newCheckedIds);
    setSelectAll(newCheckedIds.length === selectedSchedules.length && selectedSchedules.length > 0);
  };

  // 处理全选变化
  const handleSelectAllChange = (checked) => {
    setSelectAll(checked);
    setCheckedIds(checked ? selectedSchedules.map(s => s.id) : []);
  };

  return (
    <Modal
      visible={visible}
      title={`排班管理 - ${selectedDate || '未选择日期'}`}
      onCancel={onClose}
      footer={null}
      width={600}
    >
      <ExistingSchedules
        schedules={selectedSchedules}
        checkedIds={checkedIds}
        selectAll={selectAll}
        onCheckChange={handleCheckChange}
        onSelectAllChange={handleSelectAllChange}
        onDelete={handleDelete}
        onBatchDelete={handleBatchDelete}
      />

      <ScheduleForm
        form={form}
        autoSchedule={autoSchedule}
        onAutoScheduleChange={setAutoSchedule}
        onDateRangeChange={setAutoDateRange}
      />

      <Form.Item>
        <Space>
          <Button type="primary" onClick={handleAdd} icon={<PlusOutlined />}>
            {autoSchedule ? '自动排班' : '添加排班'}
          </Button>
          <Button onClick={onClose}>取消</Button>
        </Space>
      </Form.Item>
    </Modal>
  );
}

export default ScheduleModal;
