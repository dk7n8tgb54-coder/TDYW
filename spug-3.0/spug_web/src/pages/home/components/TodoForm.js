/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Form, Input, Select, DatePicker, Button, Space } from 'antd';
import moment from 'moment';

const { Option } = Select;
const { TextArea } = Input;

export default function TodoForm({ form, loading, record, onSubmit, onCancel }) {
  const handleSubmit = () => {
    const formData = form.getFieldsValue();
    if (formData.due_date) {
      formData.due_date = moment(formData.due_date).format('YYYY-MM-DD HH:mm:ss');
    }
    if (record?.id) {
      formData.id = record.id;
    }
    onSubmit(formData);
  };

  return (
    <div style={{ padding: '16px 0' }}>
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        <Form.Item
          name="title"
          label="待办事项"
          rules={[{ required: true, message: '请输入待办事项' }]}
        >
          <Input placeholder="请输入待办事项" />
        </Form.Item>

        <Form.Item name="description" label="描述">
          <TextArea rows={3} placeholder="请输入描述" />
        </Form.Item>

        <Form.Item name="priority" label="优先级" initialValue="medium">
          <Select>
            <Option value="high">高</Option>
            <Option value="medium">中</Option>
            <Option value="low">低</Option>
          </Select>
        </Form.Item>

        <Form.Item name="due_date" label="截止日期">
          <DatePicker
            showTime
            style={{ width: '100%' }}
            format="YYYY-MM-DD HH:mm:ss"
          />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={loading}>
              保存
            </Button>
            <Button onClick={onCancel}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </div>
  );
}
