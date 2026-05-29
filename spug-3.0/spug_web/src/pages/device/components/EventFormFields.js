/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Form, Input, DatePicker, Row, Col } from 'antd';

const { TextArea } = Input;

// 维修/更新共用字段
export function MaintenanceFields({ isUpdate }) {
  const timeLabel = isUpdate ? '更新时间' : '维修时间';
  const titleLabel = isUpdate ? '更新标题' : '维修标题';

  return (
    <Row gutter={16}>
      <Col span={12}>
        <Form.Item
          name="event_time"
          label={timeLabel}
          rules={[{ required: true, message: `请选择${timeLabel}` }]}
        >
          <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder={`请选择${timeLabel}`} />
        </Form.Item>
        <Form.Item
          name="event_title"
          label={titleLabel}
          rules={[{ required: true, message: `请输入${titleLabel}` }]}
        >
          <Input placeholder={`请输入${titleLabel}`} />
        </Form.Item>
        <Form.Item
          name="maintenance_measures"
          label="简要情况"
          rules={[{ required: true, message: '请填写简要情况' }]}
        >
          <TextArea rows={4} placeholder="请填写简要情况" />
        </Form.Item>
      </Col>
      <Col span={12}>
        <Form.Item
          name="related_user_id"
          label="记录人"
          rules={[{ required: true, message: '请输入记录人' }]}
        >
          <Input placeholder="请输入记录人" />
        </Form.Item>
        <Form.Item
          name="remark"
          label="备注"
        >
          <TextArea rows={4} placeholder="请输入备注" />
        </Form.Item>
      </Col>
    </Row>
  );
}

// 检修字段
export function InspectionFields() {
  return (
    <Row gutter={16}>
      <Col span={12}>
        <Form.Item
          name="event_time"
          label="故障时间"
          rules={[{ required: true, message: '请选择故障时间' }]}
        >
          <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="请选择故障时间" />
        </Form.Item>
        <Form.Item
          name="event_title"
          label="检修标题"
          rules={[{ required: true, message: '请输入检修标题' }]}
        >
          <Input placeholder="请输入检修标题" />
        </Form.Item>
        <Form.Item
          name="fault_part"
          label="故障件"
          rules={[{ required: true, message: '请填写故障件' }]}
        >
          <Input placeholder="如: 主机电源模块" />
        </Form.Item>
        <Form.Item
          name="fault_phenomenon_cause"
          label="故障现象及原因"
          rules={[{ required: true, message: '请填写故障现象及原因' }]}
        >
          <TextArea rows={3} placeholder="请填写故障现象及原因" />
        </Form.Item>
        <Form.Item
          name="maintenance_measures"
          label="检修措施"
          rules={[{ required: true, message: '请填写检修措施' }]}
        >
          <TextArea rows={3} placeholder="请填写检修措施" />
        </Form.Item>
      </Col>
      <Col span={12}>
        <Form.Item
          name="related_user_id"
          label="检修人"
          rules={[{ required: true, message: '请输入检修人' }]}
        >
          <Input placeholder="请输入检修人" />
        </Form.Item>
        <Form.Item
          name="repair_time"
          label="修复时间"
          rules={[{ required: true, message: '请选择修复时间' }]}
        >
          <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="请选择修复时间" />
        </Form.Item>
        <Form.Item
          name="remark"
          label="备注"
        >
          <TextArea rows={4} placeholder="请输入备注" />
        </Form.Item>
      </Col>
    </Row>
  );
}
