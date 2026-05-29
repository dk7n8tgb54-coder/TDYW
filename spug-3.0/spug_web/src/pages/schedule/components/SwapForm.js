/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 换班申请表单组件
 */
import React from 'react';
import { Form, Input, Select, DatePicker, Row, Col } from 'antd';
import moment from 'moment';

function SwapForm({
  form,
  store,
  fromStaffSchedules,
  toStaffSchedules,
  fromDate,
  toDate,
  onFromDateChange,
  onToDateChange,
  onFromStaffChange,
  onToStaffChange
}) {
  const handleFromDateChange = (date) => {
    const dateStr = date ? moment(date).format('YYYY-MM-DD') : '';
    onFromDateChange(dateStr);
    form.setFieldsValue({ from_staff_id: undefined, from_shift_id: undefined });
  };

  const handleToDateChange = (date) => {
    const dateStr = date ? moment(date).format('YYYY-MM-DD') : '';
    onToDateChange(dateStr);
    form.setFieldsValue({ to_staff_id: undefined, to_shift_id: undefined });
  };

  const handleFromStaffChange = (staffId) => {
    const schedule = fromStaffSchedules.find(s => s.staff_id === staffId);
    if (schedule) {
      form.setFieldsValue({ from_shift_id: schedule.shift_id });
    }
    onFromStaffChange(staffId);
  };

  const handleToStaffChange = (staffId) => {
    const schedule = toStaffSchedules.find(s => s.staff_id === staffId);
    if (schedule) {
      form.setFieldsValue({ to_shift_id: schedule.shift_id });
    }
    onToStaffChange(staffId);
  };

  return (
    <Form form={form} layout="vertical">
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item label="换出日期" name="from_date" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" onChange={handleFromDateChange} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item label="换入日期" name="to_date" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" onChange={handleToDateChange} />
          </Form.Item>
        </Col>
      </Row>

      {fromDate && toDate && (
        <>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="换出人" name="from_staff_id" rules={[{ required: true }]}>
                <Select placeholder="请选择" showSearch onChange={handleFromStaffChange}>
                  {fromStaffSchedules.map(s => {
                    const staff = store.staffList.find(x => x.id === s.staff_id);
                    if (!staff) return null;
                    return (
                      <Select.Option key={staff.id} value={staff.id}>
                        {staff.user_name} ({s.shift_name})
                      </Select.Option>
                    );
                  })}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="换入人" name="to_staff_id" rules={[{ required: true }]}>
                <Select placeholder="请选择" showSearch onChange={handleToStaffChange}>
                  {toStaffSchedules.map(s => {
                    const staff = store.staffList.find(x => x.id === s.staff_id);
                    if (!staff) return null;
                    return (
                      <Select.Option key={staff.id} value={staff.id}>
                        {staff.user_name} ({s.shift_name})
                      </Select.Option>
                    );
                  })}
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="from_shift_id" style={{ display: 'none' }}><Input /></Form.Item>
          <Form.Item name="to_shift_id" style={{ display: 'none' }}><Input /></Form.Item>
        </>
      )}

      <Form.Item label="换班原因" name="reason">
        <Input.TextArea rows={3} placeholder="请输入换班原因" />
      </Form.Item>

      {(!fromDate || !toDate) && (
        <div style={{ color: '#999', textAlign: 'center', padding: '20px' }}>
          请先选择换出和换入日期
        </div>
      )}
    </Form>
  );
}

export default SwapForm;
