/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 替班申请表单组件
 */
import React from 'react';
import { Form, Input, Select, DatePicker } from 'antd';
import moment from 'moment';

function SubstituteForm({ form, store, dateSchedules, selectedDate, onDateChange, onStaffChange }) {
  const handleDateChange = (date) => {
    const dateStr = date ? moment(date).format('YYYY-MM-DD') : '';
    onDateChange(dateStr);

    form.setFieldsValue({
      original_staff_id: undefined,
      substitute_staff_id: undefined,
      shift_id: undefined,
      shift_name: undefined
    });
  };

  const handleOriginalStaffChange = (staffId) => {
    const schedule = dateSchedules.find(s => s.staff_id === staffId);
    if (schedule) {
      form.setFieldsValue({
        shift_id: schedule.shift_id,
        shift_name: schedule.shift_name
      });
    }
    onStaffChange(staffId);
  };

  return (
    <Form form={form} layout="vertical">
      <Form.Item
        label="替班日期"
        name="date"
        rules={[{ required: true, message: '请选择替班日期' }]}
      >
        <DatePicker
          style={{ width: '100%' }}
          format="YYYY-MM-DD"
          onChange={handleDateChange}
        />
      </Form.Item>

      {dateSchedules.length > 0 && (
        <>
          <Form.Item
            label="原值班人"
            name="original_staff_id"
            rules={[{ required: true, message: '请选择原值班人' }]}
          >
            <Select
              placeholder="请选择原值班人"
              showSearch
              onChange={handleOriginalStaffChange}
            >
              {dateSchedules.map(schedule => {
                const staff = store.staffList.find(s => s.id === schedule.staff_id);
                if (!staff) return null;
                return (
                  <Select.Option key={staff.id} value={staff.id}>
                    {staff.user_name} ({schedule.shift_name})
                    {staff.department && ` - ${staff.department}`}
                  </Select.Option>
                );
              })}
            </Select>
          </Form.Item>

          <Form.Item
            label="替班人"
            name="substitute_staff_id"
            rules={[{ required: true, message: '请选择替班人' }]}
          >
            <Select placeholder="请选择替班人" showSearch>
              {store.staffList.map(staff => (
                <Select.Option key={staff.id} value={staff.id}>
                  {staff.user_name}
                  {staff.department && ` - ${staff.department}`}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="shift_id" style={{ display: 'none' }}>
            <Input />
          </Form.Item>
          <Form.Item name="shift_name" style={{ display: 'none' }}>
            <Input />
          </Form.Item>
        </>
      )}

      <Form.Item label="替班原因" name="reason">
        <Input.TextArea rows={3} placeholder="请输入替班原因" />
      </Form.Item>

      {!selectedDate && (
        <div style={{ color: '#999', textAlign: 'center', padding: '20px' }}>
          请先选择替班日期
        </div>
      )}
    </Form>
  );
}

export default SubstituteForm;
