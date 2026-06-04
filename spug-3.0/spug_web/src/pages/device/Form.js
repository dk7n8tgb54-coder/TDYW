/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, DatePicker, Select, message, Row, Col, Divider } from 'antd';
import store from './store';
import moment from 'moment';

export default observer(function () {
  const [form] = Form.useForm();
  const isEdit = !!store.record.id;

  const handleSubmit = () => {
    form.validateFields().then(values => {
      const data = {
        ...values,
        install_time: values.install_time ? values.install_time.format('YYYY-MM-DD') : '',
        enable_time: values.enable_time ? values.enable_time.format('YYYY-MM-DD') : ''
      };
      if (isEdit) {
        data.id = store.record.id;
        store.handleUpdate(data).then(() => message.success('保存成功'));
      } else {
        store.handleAdd(data).then(() => message.success('保存成功'));
      }
    });
  };

  return (
    <Modal
      visible={store.formVisible}
      title={isEdit ? '编辑设备档案' : '新增设备档案'}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
      width={900}
      okText="保存"
      cancelText="取消"
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          ...store.record,
          install_time: store.record.install_time ? moment(store.record.install_time, 'YYYY-MM-DD') : null,
          enable_time: store.record.enable_time ? moment(store.record.enable_time, 'YYYY-MM-DD') : null
        }}
      >
        {/* 基础信息栏 + 扩展信息栏 */}
        <Row gutter={16}>
          <Col span={12}>
            <div style={{ marginBottom: 16, fontWeight: 500, color: '#1890ff' }}>基础信息栏</div>
            <Form.Item
              name="device_sn"
              label="设备资产编号"
              rules={[{ required: true, message: '请输入设备资产编号' }]}
            >
              <Input placeholder="如: TD-YW-2026001" disabled={isEdit} />
            </Form.Item>
            <Form.Item
              name="device_name"
              label="设备名称"
              rules={[{ required: true, message: '请输入设备名称' }]}
            >
              <Input placeholder="请输入设备名称" />
            </Form.Item>
            <Form.Item
              name="device_model"
              label="设备型号"
              rules={[{ required: true, message: '请输入设备型号' }]}
            >
              <Input placeholder="请输入设备型号" />
            </Form.Item>
            <Form.Item
              name="frequency"
              label="工作频率"
            >
              <Input placeholder="如: 156.800MHz" />
            </Form.Item>
            <Form.Item
              name="call_sign"
              label="设备呼号"
            >
              <Input placeholder="如: 烟台台01" />
            </Form.Item>
            <Form.Item
              name="install_location"
              label="安装地点"
              rules={[{ required: true, message: '请输入安装地点' }]}
            >
              <Input placeholder="如: 福山机房A区3号机柜U12" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 16, fontWeight: 500, color: '#1890ff' }}>扩展信息栏</div>
            <Form.Item
              name="device_purpose"
              label="设备用途"
            >
              <Input.TextArea rows={3} placeholder="请输入设备用途" maxLength={500} showCount />
            </Form.Item>
            <Form.Item
              name="geo_coordinate"
              label="安装经纬度"
            >
              <Input placeholder="格式: 经度,纬度，如: 121.2563,37.5214" />
            </Form.Item>
            <Form.Item
              name="remark"
              label="备注"
            >
              <Input.TextArea rows={4} placeholder="请输入备注" maxLength={1000} showCount />
            </Form.Item>
          </Col>
        </Row>

        <Divider />

        {/* 时间/单位栏 + 负责人/状态栏 */}
        <Row gutter={16}>
          <Col span={12}>
            <div style={{ marginBottom: 16, fontWeight: 500, color: '#1890ff' }}>时间/单位栏</div>
            <Form.Item
              name="manufacturer"
              label="生产厂家"
              rules={[{ required: true, message: '请输入生产厂家' }]}
            >
              <Input placeholder="请输入生产厂家" />
            </Form.Item>
            <Form.Item
              name="install_unit"
              label="安装单位"
              rules={[{ required: true, message: '请输入安装单位' }]}
            >
              <Input placeholder="请输入安装单位" />
            </Form.Item>
            <Form.Item
              name="use_unit"
              label="使用单位"
              rules={[{ required: true, message: '请输入使用单位' }]}
            >
              <Input placeholder="请输入使用单位" />
            </Form.Item>
            <Form.Item
              name="install_time"
              label="安装时间"
              rules={[{ required: true, message: '请选择安装时间' }]}
            >
              <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" placeholder="请选择安装时间" />
            </Form.Item>
            <Form.Item
              name="enable_time"
              label="启用时间"
              rules={[{ required: true, message: '请选择启用时间' }]}
            >
              <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" placeholder="请选择启用时间" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 16, fontWeight: 500, color: '#1890ff' }}>负责人/状态栏</div>
            <Form.Item
              name="responsible_user_id"
              label="设备负责人"
              rules={[{ required: true, message: '请选择设备负责人' }]}
            >
              <UserSelect />
            </Form.Item>
            <Form.Item
              name="current_status"
              label="当前设备状况"
              rules={[{ required: true, message: '请选择当前设备状况' }]}
            >
              <Select placeholder="请选择当前设备状况">
                <Select.Option value="1">正常</Select.Option>
                <Select.Option value="2">故障</Select.Option>
                <Select.Option value="3">维修中</Select.Option>
                <Select.Option value="4">停用</Select.Option>
                <Select.Option value="5">报废</Select.Option>
              </Select>
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
})

// 用户选择组件（使用输入框避免权限问题）
function UserSelect({ value, onChange }) {
  return (
    <Input
      value={value}
      onChange={onChange}
      placeholder="请输入设备负责人姓名"
    />
  );
}

