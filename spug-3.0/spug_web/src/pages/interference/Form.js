/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Descriptions } from 'antd';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);

  function handleSubmit() {
    form.validateFields().then(() => {
      setLoading(true);
      const formData = form.getFieldsValue();
      formData['id'] = S.record.id;
      // 转换日期时间格式
      if (formData['datetime']) {
        formData['datetime'] = formData['datetime'].format('YYYY-MM-DD HH:mm:ss');
      }
      http.post('/api/interference/', formData)
        .then(() => {
          message.success('操作成功');
          S.formVisible = false;
          S.fetchRecords();
        })
        .catch(e => {
          // 【优化】添加错误提示和日志
          console.error('[干扰] 提交表单失败:', e);
          message.error(e.message || '操作失败，请稍后重试');
        })
        .finally(() => setLoading(false));
    });
  }

  // 【优化】修复 useEffect 依赖，移除 S.record.id 和 S.record.isViewMode
  React.useEffect(() => {
    const isViewDisabled = !hasPermission('interference.interference.edit');
    setViewMode(!!S.record.id && (S.record.isViewMode || isViewDisabled));

    const initialValues = {...S.record};
    if (initialValues.datetime) {
      initialValues.datetime = moment(initialValues.datetime);
    }
    form.setFieldsValue(initialValues);

    return () => {
      form.resetFields();
    };
  }, [form]);

  const info = S.record;

  if (viewMode) {
    return (
      <Modal
        visible
        width={800}
        title="干扰信息统计详情"
        footer={[
          <Button key="close" onClick={() => S.formVisible = false}>关闭</Button>
        ]}
        onCancel={() => S.formVisible = false}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="频率">{info.frequency}</Descriptions.Item>
          <Descriptions.Item label="汇报科室">{info.report_dept}</Descriptions.Item>
          <Descriptions.Item label="日期时间">{info.datetime}</Descriptions.Item>
          <Descriptions.Item label="坐标">{info.coordinates}</Descriptions.Item>
          <Descriptions.Item label="干扰类型">{info.interference_type}</Descriptions.Item>
          <Descriptions.Item label="是否上报">{info.is_reported}</Descriptions.Item>
          <Descriptions.Item label="航班号">{info.flight_number || '-'}</Descriptions.Item>
          <Descriptions.Item label="机型">{info.aircraft_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="现象" span={2}>
            <div style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto' }}>
              {info.phenomenon}
            </div>
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    )
  }

  const initialValues = {...info};
  if (initialValues.datetime) {
    initialValues.datetime = moment(initialValues.datetime);
  }

  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={S.record.id ? '编辑干扰记录' : '新建干扰记录'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item name="frequency" label="频率"
                   rules={[
                     { required: true, message: '请输入频率' },
                     { pattern: /^\d+(\.\d+)?$/, message: '频率请输入数字' }
                   ]}>
          <Input placeholder="请输入频率"/>
        </Form.Item>
        <Form.Item name="report_dept" label="汇报科室"
                   rules={[{ required: true, message: '请输入汇报科室' }]}>
          <Input placeholder="请输入汇报科室"/>
        </Form.Item>
        <Form.Item name="datetime" label="日期时间"
                   rules={[{ required: true, message: '请选择日期时间' }]}>
          <DatePicker showTime style={{width: '100%'}} placeholder="请选择日期时间"/>
        </Form.Item>
        <Form.Item name="coordinates" label="坐标"
                   rules={[{ required: true, message: '请输入坐标' }]}>
          <Input placeholder="请输入坐标"/>
        </Form.Item>
        <Form.Item name="interference_type" label="干扰类型"
                   rules={[{ required: true, message: '请输入干扰类型' }]}>
          <Input placeholder="请输入干扰类型"/>
        </Form.Item>
        <Form.Item name="phenomenon" label="现象"
                   rules={[{ required: true, message: '请输入现象' }]}>
          <Input.TextArea rows={4} placeholder="请输入现象"/>
        </Form.Item>
        <Form.Item name="flight_number" label="航班号">
          <Input placeholder="请输入航班号（非必填）"/>
        </Form.Item>
        <Form.Item name="aircraft_type" label="机型">
          <Input placeholder="请输入机型（非必填）"/>
        </Form.Item>
        <Form.Item name="is_reported" label="是否上报"
                   rules={[{ required: true, message: '请选择是否上报' }]}>
          <Select placeholder="请选择是否上报">
            <Select.Option value="是">是</Select.Option>
            <Select.Option value="否">否</Select.Option>
          </Select>
        </Form.Item>
      </Form>
    </Modal>
  )
})
