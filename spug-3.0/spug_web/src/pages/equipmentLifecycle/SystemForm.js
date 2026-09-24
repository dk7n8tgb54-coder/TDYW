/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统新增/编辑弹窗（聚合提交）。
 * 固定基础字段 + 扩展信息（呼号 / 安装经纬度 / 工作频率，均选填）一次填写、
 * 一次提交。（自定义字段机制已下线，原内联新增字段入口一并移除。）
 */
import React, { useState, useEffect, useRef } from 'react';
import moment from 'moment';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, DatePicker, Row, Col, Divider, Tag,
} from 'antd';
import store from './store';
import { HEALTH_STATUS_COLOR } from './constants';

const {TextArea} = Input;

/** 固定基础字段区（健康状态只读展示，由故障/工单统一计算）。 */
function BasicFields({record}) {
  const isEdit = !!record.id;
  return (
    <Row gutter={16}>
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
          name="system_purpose"
          label="系统用途"
          rules={[{max: 500, message: '长度不能超过 500'}]}
        >
          <TextArea rows={2} placeholder="选填"/>
        </Form.Item>
      </Col>
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
          <DatePicker format="YYYY-MM-DD" style={{width: '100%'}}/>
        </Form.Item>
      </Col>
      <Col span={12}>
        <Form.Item name="enable_time" label="启用时间" rules={[{required: true, message: '请选择启用时间'}]}>
          <DatePicker format="YYYY-MM-DD" style={{width: '100%'}}/>
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
        <Form.Item label="运行健康状态" tooltip="由故障与工单统一计算，不能手动修改">
          {isEdit && record.health_status_text
            ? <Tag color={HEALTH_STATUS_COLOR[record.health_status]} style={{fontSize: 14, padding: '2px 10px'}}>
                {record.health_status_text}
              </Tag>
            : <Tag color={HEALTH_STATUS_COLOR.normal} style={{fontSize: 14, padding: '2px 10px'}}>正常</Tag>}
        </Form.Item>
      </Col>
      <Col span={12}>
        <Form.Item name="remark" label="备注" rules={[{max: 1000, message: '长度不能超过 1000'}]}>
          <TextArea rows={2} placeholder="选填"/>
        </Form.Item>
      </Col>
    </Row>
  );
}

/** 扩展信息区：呼号 / 安装经纬度 / 工作频率，全部选填。 */
function ExtendedFields() {
  return (
    <>
      <Divider orientation="left" plain>扩展信息（选填）</Divider>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="callsign" label="呼号" rules={[{max: 50, message: '长度不能超过 50'}]}>
            <Input placeholder="选填"/>
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
        <Col span={12}>
          <Form.Item name="work_frequency" label="工作频率" rules={[{max: 100, message: '长度不能超过 100'}]}>
            <Input placeholder="选填，如 438.500MHz 或频段范围"/>
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}

function SystemForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);
  const record = store.record;
  const isEdit = !!record.id;

  useEffect(() => {
    if (!isEdit) return;
    form.setFieldsValue({
      name: record.name,
      system_model: record.system_model,
      install_location: record.install_location,
      geo_coordinate: record.geo_coordinate,
      callsign: record.callsign,
      work_frequency: record.work_frequency,
      system_purpose: record.system_purpose,
      manufacturer: record.manufacturer,
      install_unit: record.install_unit,
      use_unit: record.use_unit,
      install_time: record.install_time ? moment(record.install_time) : undefined,
      enable_time: record.enable_time ? moment(record.enable_time) : undefined,
      responsible_user_name: record.responsible_user_name,
      remark: record.remark,
    });
  }, []);

  function buildPayload(values) {
    const system = {
      name: values.name,
      system_model: values.system_model,
      install_location: values.install_location,
      geo_coordinate: values.geo_coordinate || '',
      callsign: values.callsign || '',
      work_frequency: values.work_frequency || '',
      system_purpose: values.system_purpose || '',
      manufacturer: values.manufacturer,
      install_unit: values.install_unit,
      use_unit: values.use_unit,
      install_time: values.install_time ? values.install_time.format('YYYY-MM-DD') : undefined,
      enable_time: values.enable_time ? values.enable_time.format('YYYY-MM-DD') : undefined,
      responsible_user_name: values.responsible_user_name,
      remark: values.remark || '',
    };
    // 系统编号由后端自动生成，前端不传
    return {system};
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      setLoading(true);
      store.submitForm(buildPayload(values))
        .catch(() => {})
        .finally(() => {
          if (mountedRef.current) setLoading(false);
        });
    }).catch(() => {});
  }

  return (
    <Modal
      visible
      width={960}
      maskClosable={false}
      title={isEdit ? '编辑系统' : '新增系统'}
      okText={isEdit ? '保 存' : '确 定'}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 17}}>
        <BasicFields record={record}/>
        <ExtendedFields/>
      </Form>
    </Modal>
  );
}

export default observer(SystemForm);
