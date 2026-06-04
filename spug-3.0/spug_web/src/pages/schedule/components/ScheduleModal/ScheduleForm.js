/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 排班表单组件
 * 
 * 包含：
 * - 人员选择
 * - 班次选择
 * - 自动排班选项
 * - 备注输入
 */
import React from 'react';
import { Form, Select, Checkbox, DatePicker, Input } from 'antd';
import store from '../../stores';

const { Option } = Select;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

/**
 * 人员选择器组件
 */
export const StaffSelect = () => (
  <Form.Item
    label="值班人员"
    name="staff_id"
    rules={[{ required: true, message: '请选择值班人员' }]}
  >
    <Select placeholder="请选择值班人员" showSearch>
      {store.staffList.filter(s => s.is_active).map(staff => (
        <Option key={staff.id} value={staff.id}>
          {staff.user_name}
          {staff.department && ` (${staff.department})`}
        </Option>
      ))}
    </Select>
  </Form.Item>
);

/**
 * 班次选择器组件
 */
export const ShiftSelect = () => (
  <Form.Item
    label="班次"
    name="shift_id"
    rules={[{ required: true, message: '请选择班次' }]}
  >
    <Select placeholder="请选择班次">
      {store.shiftList.map(shift => (
        <Option key={shift.id} value={shift.id}>
          {shift.name} ({shift.shift_type === 'work_rest' ? `上${shift.work_days}休${shift.rest_days}` : '自定义'})
        </Option>
      ))}
    </Select>
  </Form.Item>
);

/**
 * 自动排班选项组件
 */
export const AutoScheduleCheckbox = ({ onChange }) => (
  <Form.Item 
    name="auto_schedule" 
    valuePropName="checked" 
    initialValue={false}
  >
    <Checkbox onChange={(e) => onChange(e.target.checked)}>
      启用自动排班
    </Checkbox>
  </Form.Item>
);

/**
 * 日期范围选择器组件
 */
export const DateRangePicker = ({ onChange }) => (
  <Form.Item
    label="排班日期范围"
    name="auto_date_range"
    rules={[{ required: true, message: '请选择排班日期范围' }]}
  >
    <RangePicker
      style={{ width: '100%' }}
      format="YYYY-MM-DD"
      placeholder={['开始日期', '结束日期']}
      onChange={(dates) => onChange(dates)}
    />
  </Form.Item>
);

/**
 * 备注输入组件
 */
export const NotesInput = () => (
  <Form.Item label="备注" name="notes">
    <TextArea placeholder="请输入备注" rows={2} />
  </Form.Item>
);

/**
 * 排班表单主组件
 * 
 * @param {Object} props
 * @param {FormInstance} props.form - Ant Design Form实例
 * @param {boolean} props.autoSchedule - 是否启用自动排班
 * @param {Function} props.onAutoScheduleChange - 自动排班开关回调
 * @param {Function} props.onDateRangeChange - 日期范围变化回调
 */
function ScheduleForm({ 
  form, 
  autoSchedule, 
  onAutoScheduleChange, 
  onDateRangeChange 
}) {
  return (
    <Form form={form} layout="vertical">
      <h4>添加排班:</h4>
      
      <StaffSelect />
      <ShiftSelect />
      
      <AutoScheduleCheckbox onChange={onAutoScheduleChange} />
      
      {autoSchedule && (
        <DateRangePicker onChange={onDateRangeChange} />
      )}
      
      <NotesInput />
    </Form>
  );
}

export default ScheduleForm;
