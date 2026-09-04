/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, DatePicker, Select, message, Row, Col } from 'antd';
import moment from 'moment';
import store from './store';
import { DEVICE_STATUS_OPTIONS } from './constants';

/**
 * 设备档案新建/编辑弹窗（equipment_lifecycle.device.manage）
 * 字段从简：编号/名称/型号/状态/安装时间/启用时间/备注。
 * 当前位置仅新建时可填写（建档后通过独立的"变更位置"接口修改，
 * 普通编辑不提交该字段，避免静默覆盖位置历史）。
 * 数据存于设备生命周期独立档案表，与旧设备管理模块无关。
 */
export default observer(function () {
  const [form] = Form.useForm();
  const isEdit = !!store.record.id;

  const handleSubmit = () => {
    form.validateFields().then(values => {
      const data = {
        device_sn: (values.device_sn || '').trim(),
        device_name: (values.device_name || '').trim(),
        device_model: (values.device_model || '').trim(),
        current_status: values.current_status,
        install_time: values.install_time ? values.install_time.format('YYYY-MM-DD') : '',
        enable_time: values.enable_time ? values.enable_time.format('YYYY-MM-DD') : '',
        remark: (values.remark || '').trim(),
      };
      if (!isEdit) data.current_location = (values.current_location || '').trim();
      const request = isEdit
        ? store.handleUpdate({...data, id: store.record.id})
        : store.handleAdd(data);
      request.then(() => message.success('保存成功'));
    }).catch(() => {});
  };

  return (
    <Modal
      visible={store.formVisible}
      title={isEdit ? '编辑设备档案' : '新增设备档案'}
      onCancel={() => store.closeForm()}
      onOk={handleSubmit}
      okText="保存"
      cancelText="取消"
      width={560}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          ...store.record,
          install_time: store.record.install_time ? moment(store.record.install_time, 'YYYY-MM-DD') : null,
          enable_time: store.record.enable_time ? moment(store.record.enable_time, 'YYYY-MM-DD') : null,
        }}
      >
        <Form.Item
          name="device_sn"
          label="设备资产编号"
          rules={[{required: true, message: '请输入设备资产编号'}]}
          extra={isEdit ? '设备编号不可修改' : '租户内唯一'}
        >
          <Input placeholder="请输入设备资产编号" disabled={isEdit}/>
        </Form.Item>
        <Form.Item
          name="device_name"
          label="设备名称"
          rules={[{required: true, message: '请输入设备名称'}]}
        >
          <Input placeholder="请输入设备名称"/>
        </Form.Item>
        <Form.Item
          name="device_model"
          label="设备型号"
          rules={[{required: true, message: '请输入设备型号'}]}
        >
          <Input placeholder="请输入设备型号"/>
        </Form.Item>
        <Form.Item
          name="current_status"
          label="当前设备状况"
          rules={[{required: true, message: '请选择当前设备状况'}]}
        >
          <Select options={DEVICE_STATUS_OPTIONS} placeholder="请选择当前设备状况"/>
        </Form.Item>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="install_time" label="安装时间">
              <DatePicker style={{width: '100%'}} format="YYYY-MM-DD" placeholder="请选择安装时间"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="enable_time" label="启用时间">
              <DatePicker style={{width: '100%'}} format="YYYY-MM-DD" placeholder="请选择启用时间"/>
            </Form.Item>
          </Col>
        </Row>
        {!isEdit && (
          <Form.Item
            name="current_location"
            label="当前位置"
            extra="建档后可通过详情中的「变更位置」修改"
          >
            <Input placeholder="请输入当前所在位置（可留空）" maxLength={200}/>
          </Form.Item>
        )}
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} placeholder="请输入备注" maxLength={500} showCount/>
        </Form.Item>
      </Form>
    </Modal>
  );
})
