/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, DatePicker, Select } from 'antd';
import moment from 'moment';
import store from './store';
import { LOCATION_CHANGE_TYPE_OPTIONS } from './constants';

/**
 * 设备位置变更弹窗（独立接口，equipment_lifecycle.device.manage）。
 * 原位置由服务端读取，前端仅展示；设备已有位置时变更原因必填。
 * 成功后由 store 重新拉取详情与列表，不做乐观更新。
 */
export default observer(function LocationChangeForm() {
  const [form] = Form.useForm();
  const record = store.record || {};
  const isFirstEntry = !record.current_location;

  const handleSubmit = () => {
    form.validateFields().then(values => {
      store.changeLocation({
        new_location: (values.new_location || '').trim(),
        effective_at: values.effective_at ? values.effective_at.format('YYYY-MM-DD HH:mm:ss') : '',
        change_type: values.change_type,
        reason: (values.reason || '').trim(),
      }).catch(() => {});
    }).catch(() => {});
  };

  return (
    <Modal
      visible={store.locationChangeVisible}
      title="变更位置"
      onCancel={store.closeLocationChange}
      onOk={handleSubmit}
      okText="确定"
      cancelText="取消"
      width={520}
      maskClosable={false}
    >
      <Form form={form} layout="vertical" initialValues={{
        effective_at: moment(),
        change_type: 'relocation',
      }}>
        <Form.Item label="当前位置">
          {record.current_location || '（无，本次为首次登记）'}
        </Form.Item>
        <Form.Item
          name="new_location"
          label="新位置"
          rules={[{required: true, message: '请输入新位置'}]}
        >
          <Input placeholder="请输入新位置，如：一号机房-A区-机柜03-机位12" maxLength={200}/>
        </Form.Item>
        <Form.Item name="change_type" label="变更类型" rules={[{required: true, message: '请选择变更类型'}]}>
          <Select options={LOCATION_CHANGE_TYPE_OPTIONS} placeholder="请选择变更类型"/>
        </Form.Item>
        <Form.Item name="effective_at" label="生效时间">
          <DatePicker style={{width: '100%'}} showTime format="YYYY-MM-DD HH:mm:ss"
                      placeholder="默认当前时间"/>
        </Form.Item>
        <Form.Item
          name="reason"
          label="变更原因"
          rules={[{required: !isFirstEntry, message: '请输入变更原因'}]}
        >
          <Input.TextArea rows={2} placeholder="请输入变更原因" maxLength={500} showCount/>
        </Form.Item>
      </Form>
    </Modal>
  );
})
