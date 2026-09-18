/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统新增/编辑弹窗。
 * 分栏延续设备档案习惯：基础信息 / 扩展信息 / 时间与单位 / 负责人和状态。
 */
import React, { useState, useEffect } from 'react';
import moment from 'moment';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Row, Col } from 'antd';
import store from './store';
import { HEALTH_STATUS_OPTIONS } from './constants';

const {TextArea} = Input;

function SystemForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const record = store.record;
  const isEdit = !!record.id;

  useEffect(() => {
    if (!isEdit) return;
    form.setFieldsValue({
      system_code: record.system_code,
      name: record.name,
      system_type: record.system_type,
      system_model: record.system_model,
      install_location: record.install_location,
      geo_coordinate: record.geo_coordinate,
      system_purpose: record.system_purpose,
      manufacturer: record.manufacturer,
      install_unit: record.install_unit,
      use_unit: record.use_unit,
      install_time: record.install_time ? moment(record.install_time) : undefined,
      enable_time: record.enable_time ? moment(record.enable_time) : undefined,
      responsible_user_name: record.responsible_user_name,
      health_status: record.health_status,
      remark: record.remark,
    });
  }, [form, isEdit]);

  function handleSubmit() {
    form.validateFields().then(values => {
      const data = {...values};
      data.install_time = data.install_time ? data.install_time.format('YYYY-MM-DD HH:mm') : undefined;
      data.enable_time = data.enable_time ? data.enable_time.format('YYYY-MM-DD HH:mm') : undefined;
      if (isEdit) {
        // 系统编号创建后不可修改，编辑时原样回传
        data.system_code = record.system_code;
      }
      setLoading(true);
      store.submitForm(data)
        .catch(() => {})
        .finally(() => setLoading(false));
    }).catch(() => {});
  }

  const activeTypes = store.types.filter(t => t.is_active || t.id === record.system_type);
  return (
    <Modal
      visible
      width={720}
      maskClosable={false}
      title={isEdit ? '编辑系统' : '新增系统'}
      okText={isEdit ? '保 存' : '确 定'}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 17}}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="system_code"
              label="系统编号"
              rules={[
                {required: !isEdit, message: '请输入系统编号'},
                {max: 50, message: '长度不能超过 50'},
                {pattern: /^[A-Za-z0-9_-]+$/, message: '仅支持字母、数字、中划线和下划线'},
              ]}
            >
              <Input disabled={isEdit} placeholder="租户内唯一，创建后不可修改"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="name"
              label="系统名称"
              rules={[{required: true, message: '请输入系统名称'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入系统正式名称"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="system_type" label="系统类型" rules={[{required: !isEdit, message: '请选择系统类型'}]}>
              <Select
                placeholder="请选择系统类型"
                disabled={isEdit}
                notFoundContent="暂无系统类型，请先在类型管理中创建"
              >
                {activeTypes.map(t => (
                  <Select.Option value={t.id} key={t.id}>{t.name}</Select.Option>
                ))}
              </Select>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="system_model"
              label="系统型号"
              rules={[{required: true, message: '请输入系统型号'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入系统型号"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="install_location"
              label="安装地点"
              rules={[{required: true, message: '请输入安装地点'}, {max: 200, message: '长度不能超过 200'}]}
            >
              <Input placeholder="请输入安装地点"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="geo_coordinate"
              label="安装经纬度"
              rules={[{pattern: /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/, message: '格式: 经度,纬度'}]}
            >
              <Input placeholder="选填，格式: 经度,纬度"/>
            </Form.Item>
          </Col>
        </Row>
        <Form.Item labelCol={{span: 3}} wrapperCol={{span: 20}} name="system_purpose" label="系统用途"
                   rules={[{max: 500, message: '长度不能超过 500'}]}>
          <TextArea rows={2} placeholder="选填"/>
        </Form.Item>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="manufacturer"
              label="生产厂家"
              rules={[{required: true, message: '请输入生产厂家'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入生产厂家"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="install_unit"
              label="安装单位"
              rules={[{required: true, message: '请输入安装单位'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入安装单位"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="use_unit"
              label="使用单位"
              rules={[{required: true, message: '请输入使用单位'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入使用单位"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="install_time" label="安装时间" rules={[{required: true, message: '请选择安装时间'}]}>
              <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="enable_time" label="启用时间" rules={[{required: true, message: '请选择启用时间'}]}>
              <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="responsible_user_name"
              label="系统负责人"
              rules={[{required: true, message: '请输入系统负责人'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入负责人姓名"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="health_status" label="运行健康状态" rules={[{required: true, message: '请选择运行健康状态'}]}>
              <Select placeholder="请选择运行健康状态">
                {HEALTH_STATUS_OPTIONS.map(item => (
                  <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
                ))}
              </Select>
            </Form.Item>
          </Col>
        </Row>
        <Form.Item labelCol={{span: 3}} wrapperCol={{span: 20}} name="remark" label="备注"
                   rules={[{max: 1000, message: '长度不能超过 1000'}]}>
          <TextArea rows={2} placeholder="选填"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default observer(SystemForm);
